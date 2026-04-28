import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.fhir_queries import build_fhir_match_sql, parse_search_query_to_terms
from src.agents.prompts import get_prompt
from src.agents.root_word_search_agent import _TSVECTOR_EXPR, DEMOGRAPHIC_FIELDS
from src.agents.text_to_sql_agent import TextToSQLAgent
from src.core.config import settings
from src.services.pipeline_cache import DbPipelineCache

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "agent_results"

_AGE_RE = re.compile(r"(\d+)\s*(?:years?|yrs?)?", re.IGNORECASE)


def _parse_age(value: str | None) -> int | None:
    if not value:
        return None
    match = _AGE_RE.search(value)
    return int(match.group(1)) if match else None


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


_LLM_TIMEOUT = 30
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


class TrialMatchOrchestrator:
    """Chains Text-to-SQL (LLM pre-filter) + Root Word Search (stemming
    verification) + demographic filters to match patients to a trial.

    Production features:
    - Stage 1 results cached per trial (5 min TTL) to avoid redundant LLM calls
    - Per-stage timing in milliseconds for performance monitoring
    - Intermediate results saved to agent_results/ for audit trail
    - Fallback to full-DB search if LLM fails or returns 0
    """

    PROMPTS_FILE = "text_to_sql.yaml"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.text_to_sql = TextToSQLAgent(session)
        self.pipeline_cache = DbPipelineCache(session)
        self._llm_client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            timeout=_LLM_TIMEOUT,
        )

    async def extract_criteria_from_text(self, raw_text: str) -> dict:
        """Use an LLM to parse free-text into structured search parameters."""
        system_prompt = get_prompt(
            "criteria_extraction", role="system", prompts_file=self.PROMPTS_FILE,
        )
        user_prompt = get_prompt(
            "criteria_extraction", role="user", prompts_file=self.PROMPTS_FILE,
            raw_text=raw_text,
        )

        response = await asyncio.wait_for(
            self._llm_client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=512,
            ),
            timeout=_LLM_TIMEOUT,
        )

        content = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        match = _JSON_FENCE_RE.search(content)
        if match:
            content = match.group(1).strip()

        parsed = json.loads(content)
        logger.info("Criteria extracted from free text", extra={"raw": raw_text, "parsed": parsed})
        return parsed

    async def fetch_trial(self, trial_id: str) -> dict | None:
        result = await self.session.execute(
            text("""
                SELECT id, nct_id, title, sponsor, status, payload
                FROM clinical_trials
                WHERE nct_id = :tid OR id::text = :tid
                LIMIT 1
            """),
            {"tid": trial_id},
        )
        row = result.fetchone()
        if not row:
            return None

        cols = list(result.keys())
        return dict(zip(cols, row))

    def extract_criteria(self, trial: dict) -> dict:
        payload = trial.get("payload", {})

        conditions = payload.get("conditions", [])
        keywords = payload.get("keywords", [])
        eligibility = payload.get("eligibility", {})

        search_terms = conditions + keywords
        search_query = " OR ".join(search_terms) if search_terms else ""

        sex = eligibility.get("sex", "ALL")
        min_age = _parse_age(eligibility.get("minimumAge"))
        max_age = _parse_age(eligibility.get("maximumAge"))

        location_countries = payload.get("location_countries", [])
        location_cities = payload.get("location_cities", [])

        return {
            "conditions": conditions,
            "keywords": keywords,
            "search_query": search_query,
            "sex": sex,
            "min_age": min_age,
            "max_age": max_age,
            "eligibility_text": eligibility.get("eligibilityCriteria", ""),
            "location_countries": location_countries,
            "location_cities": location_cities,
            "brief_summary": payload.get("brief_summary", ""),
        }

    async def _prefilter_with_llm(
        self, trial_id: str, criteria: dict, source: str = "kaggle",
    ) -> tuple[str | None, list[str], bool]:
        """Stage 1: LLM pre-filter with caching.

        Returns (generated_sql, patient_ids, cache_hit).
        Cache key includes source so kaggle/fhir caches don't collide.
        """
        cache_key = f"{trial_id}:{source}" if source != "kaggle" else trial_id
        cached = await self.pipeline_cache.get(cache_key)
        if cached:
            return cached["generated_sql"], cached["patient_ids"], True

        try:
            generated_sql, patient_ids = await self.text_to_sql.generate_patient_filter_sql(
                criteria, source=source,
            )
            logger.info("Text-to-SQL pre-filter: %d patients (source=%s)", len(patient_ids), source)
            await self.pipeline_cache.set(cache_key, generated_sql, patient_ids)
            return generated_sql, patient_ids, False
        except Exception as e:
            logger.warning("Text-to-SQL pre-filter failed, falling back: %s (source=%s)", e, source)
            return None, [], False

    async def match_patients(
        self,
        search_query: str,
        sex: str = "ALL",
        min_age: int | None = None,
        max_age: int | None = None,
        min_bmi: float | None = None,
        max_bmi: float | None = None,
        smoker_status: str | None = None,
        limit: int = 200,
        prefilter_patient_ids: list[str] | None = None,
        source: str = "kaggle",
    ) -> tuple[list[dict], list[str]]:
        """Stage 2: Search + demographic filters.

        When source="kaggle": tsvector search on the flat patients table.
        When source="fhir": ILIKE search on fhir_conditions + fhir_patients JOINs.
        Output shape is identical for both paths.
        """
        if source == "fhir":
            return await self._match_patients_fhir(
                search_query, sex, min_age, max_age,
                min_bmi, max_bmi, smoker_status,
                limit, prefilter_patient_ids,
            )

        # ── Kaggle path (existing logic, unchanged) ──────────────────
        where_clauses = [f"{_TSVECTOR_EXPR} @@ query"]
        params: dict = {"query": search_query, "limit": limit}

        if prefilter_patient_ids:
            placeholders = ", ".join(f":pid_{i}" for i in range(len(prefilter_patient_ids)))
            where_clauses.append(f"p.id::text IN ({placeholders})")
            for i, pid in enumerate(prefilter_patient_ids):
                params[f"pid_{i}"] = pid

        if sex and sex.upper() != "ALL":
            where_clauses.append("p.gender ILIKE :sex")
            params["sex"] = sex

        if min_age is not None:
            where_clauses.append("p.age >= :min_age")
            params["min_age"] = min_age

        if max_age is not None:
            where_clauses.append("p.age <= :max_age")
            params["max_age"] = max_age

        if min_bmi is not None:
            where_clauses.append("(p.metadata->>'bmi')::float >= :min_bmi")
            params["min_bmi"] = min_bmi

        if max_bmi is not None:
            where_clauses.append("(p.metadata->>'bmi')::float <= :max_bmi")
            params["max_bmi"] = max_bmi

        if smoker_status:
            where_clauses.append("p.metadata->>'smokerStatus' ILIKE :smoker_status")
            params["smoker_status"] = f"%{smoker_status}%"

        where_str = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                {DEMOGRAPHIC_FIELDS},
                p.conditions,
                ts_rank({_TSVECTOR_EXPR}, query) AS relevance_score
            FROM patients p,
                 websearch_to_tsquery('english', :query) AS query
            WHERE {where_str}
            ORDER BY relevance_score DESC
            LIMIT :limit
        """

        logger.info("Root word search", extra={"query": search_query,
                     "prefiltered": len(prefilter_patient_ids) if prefilter_patient_ids else "all"})
        result = await self.session.execute(text(sql), params)
        columns = list(result.keys())
        rows = result.fetchall()

        patients = []
        patient_ids = []
        for row in rows:
            d = dict(zip(columns, row))
            patient_ids.append(str(d["id"]))
            patients.append({
                "id": str(d["id"]),
                "display_patient_id": d["display_patient_id"],
                "age": d["age"],
                "gender": d["gender"],
                "ethnicity": d["ethnicity"],
                "state": d["state"],
                "country": d["country"],
                "conditions": d["conditions"],
                "bmi": float(d["bmi"]) if d.get("bmi") else None,
                "smoker_status": d.get("smoker_status"),
                "general_health": d.get("general_health"),
                "relevance_score": float(d["relevance_score"]),
            })

        return patients, patient_ids

    async def _match_patients_fhir(
        self,
        search_query: str,
        sex: str = "ALL",
        min_age: int | None = None,
        max_age: int | None = None,
        min_bmi: float | None = None,
        max_bmi: float | None = None,
        smoker_status: str | None = None,
        limit: int = 200,
        prefilter_patient_ids: list[str] | None = None,
    ) -> tuple[list[dict], list[str]]:
        """FHIR path for Stage 2: search fhir_patients + fhir_conditions."""
        search_terms = parse_search_query_to_terms(search_query)

        sql, params = build_fhir_match_sql(
            search_terms=search_terms,
            sex=sex,
            min_age=min_age,
            max_age=max_age,
            min_bmi=min_bmi,
            max_bmi=max_bmi,
            smoker_status=smoker_status,
            limit=limit,
            prefilter_patient_ids=prefilter_patient_ids,
        )

        logger.info("FHIR patient search", extra={
            "query": search_query, "terms": search_terms,
            "prefiltered": len(prefilter_patient_ids) if prefilter_patient_ids else "all",
        })
        result = await self.session.execute(text(sql), params)
        columns = list(result.keys())
        rows = result.fetchall()

        patients = []
        patient_ids = []
        for row in rows:
            d = dict(zip(columns, row))
            patient_ids.append(str(d["id"]))
            patients.append({
                "id": str(d["id"]),
                "display_patient_id": d.get("display_patient_id"),
                "age": d.get("age"),
                "gender": d.get("gender"),
                "ethnicity": d.get("ethnicity"),
                "state": d.get("state"),
                "country": d.get("country"),
                "conditions": d.get("conditions") or [],
                "bmi": float(d["bmi"]) if d.get("bmi") else None,
                "smoker_status": d.get("smoker_status"),
                "general_health": d.get("general_health"),
                "relevance_score": 1.0,
            })

        return patients, patient_ids

    async def get_total_patient_count(self, source: str = "kaggle") -> int:
        table = "fhir_patients" if source == "fhir" else "patients"
        result = await self.session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        return result.scalar()

    def _save_results(self, result: dict, prefix: str = "match") -> str:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        trial_id = result.get("trial_nct_id") or result.get("trial_id", "manual")
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(trial_id))[:30]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{safe_id}_{timestamp}.json"
        filepath = RESULTS_DIR / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)

        logger.info("Results saved", extra={"file": str(filepath)})
        return str(filepath)

    def _save_pipeline_intermediate(
        self, trial_id: str, nct_id: str | None, pipeline_info: dict,
        prefiltered_ids: list[str], verified_ids: list[str],
    ) -> str:
        """Save intermediate Stage 1 + Stage 2 results for audit trail."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(nct_id or trial_id))[:30]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = RESULTS_DIR / f"pipeline_{safe_id}_{timestamp}.json"

        intermediate = {
            "trial_id": trial_id,
            "trial_nct_id": nct_id,
            "timestamp": timestamp,
            "text_to_sql_query": pipeline_info.get("text_to_sql_query"),
            "text_to_sql_patient_count": len(prefiltered_ids),
            "text_to_sql_patient_ids": prefiltered_ids[:100],
            "root_word_patient_count": len(verified_ids),
            "root_word_patient_ids": verified_ids[:100],
            "cache_hit": pipeline_info.get("cache_hit", False),
            "timing": {
                "stage1_ms": pipeline_info.get("stage1_ms"),
                "stage2_ms": pipeline_info.get("stage2_ms"),
                "total_ms": pipeline_info.get("total_ms"),
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(intermediate, f, indent=2, default=str)

        logger.info("Pipeline intermediate saved", extra={"file": str(filepath)})
        return str(filepath)

    async def run_by_trial(self, trial_id: str, limit: int = 200, source: str = "kaggle") -> dict:
        """Full pipeline with timing, caching, and intermediate storage."""
        pipeline_start = time.perf_counter()

        trial = await self.fetch_trial(trial_id)
        if not trial:
            raise ValueError(f"Trial not found: {trial_id}")

        criteria = self.extract_criteria(trial)

        if not criteria["search_query"]:
            raise ValueError("Trial has no conditions or keywords to match against")

        total_patients = await self.get_total_patient_count(source=source)

        # Stage 1: Text-to-SQL pre-filter (with cache)
        t1 = time.perf_counter()
        generated_sql, prefiltered_ids, cache_hit = await self._prefilter_with_llm(
            trial_id, criteria, source=source,
        )
        stage1_ms = _ms(t1)
        used_prefilter = bool(prefiltered_ids)

        # Stage 2: Root Word Search (or FHIR condition search)
        t2 = time.perf_counter()
        patients, patient_ids = await self.match_patients(
            search_query=criteria["search_query"],
            sex=criteria["sex"],
            min_age=criteria["min_age"],
            max_age=criteria["max_age"],
            limit=limit,
            prefilter_patient_ids=prefiltered_ids if prefiltered_ids else None,
            source=source,
        )

        # Fallback
        if used_prefilter and not patients:
            logger.info("Pre-filtered set yielded 0, retrying without pre-filter (source=%s)", source)
            patients, patient_ids = await self.match_patients(
                search_query=criteria["search_query"],
                sex=criteria["sex"],
                min_age=criteria["min_age"],
                max_age=criteria["max_age"],
                limit=limit,
                source=source,
            )
            used_prefilter = False
        stage2_ms = _ms(t2)

        total_ms = _ms(pipeline_start)

        pipeline_info = {
            "text_to_sql_prefiltered": len(prefiltered_ids),
            "text_to_sql_query": generated_sql,
            "root_word_verified": len(patients),
            "used_prefilter": used_prefilter,
            "cache_hit": cache_hit,
            "stage1_ms": stage1_ms,
            "stage2_ms": stage2_ms,
            "total_ms": total_ms,
        }

        # Save intermediate results for audit
        self._save_pipeline_intermediate(
            str(trial["id"]), trial.get("nct_id"),
            pipeline_info, prefiltered_ids, patient_ids,
        )

        result = {
            "trial_id": str(trial["id"]),
            "trial_nct_id": trial.get("nct_id"),
            "trial_title": trial.get("title"),
            "trial_status": trial.get("status"),
            "criteria_used": {
                "conditions": criteria["conditions"],
                "keywords": criteria["keywords"],
                "search_query": criteria["search_query"],
                "sex_filter": criteria["sex"],
                "age_range": {
                    "min": criteria["min_age"],
                    "max": criteria["max_age"],
                },
                "eligibility_text": criteria["eligibility_text"][:500] if criteria["eligibility_text"] else "",
            },
            "pipeline": pipeline_info,
            "total_patients": total_patients,
            "matched_count": len(patients),
            "matched_patient_ids": patient_ids,
            "patients": patients,
        }

        saved_file = self._save_results(result)
        result["saved_to"] = saved_file

        return result

    async def run_by_criteria(
        self,
        search_query: str,
        sex: str = "ALL",
        min_age: int | None = None,
        max_age: int | None = None,
        min_bmi: float | None = None,
        max_bmi: float | None = None,
        smoker_status: str | None = None,
        limit: int = 200,
        source: str = "kaggle",
    ) -> dict:
        """Match patients using manually provided criteria (no trial lookup, no LLM)."""
        total_patients = await self.get_total_patient_count(source=source)
        patients, patient_ids = await self.match_patients(
            search_query=search_query,
            sex=sex,
            min_age=min_age,
            max_age=max_age,
            min_bmi=min_bmi,
            max_bmi=max_bmi,
            smoker_status=smoker_status,
            limit=limit,
            source=source,
        )

        result = {
            "trial_id": None,
            "trial_nct_id": None,
            "trial_title": "Manual criteria search",
            "trial_status": None,
            "criteria_used": {
                "conditions": [],
                "keywords": [],
                "search_query": search_query,
                "sex_filter": sex,
                "age_range": {"min": min_age, "max": max_age},
                "eligibility_text": "",
            },
            "total_patients": total_patients,
            "matched_count": len(patients),
            "matched_patient_ids": patient_ids,
            "patients": patients,
        }

        saved_file = self._save_results(result)
        result["saved_to"] = saved_file

        return result
