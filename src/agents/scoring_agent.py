import csv
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.trial_match_orchestrator import TrialMatchOrchestrator
from src.db.models.scoring import ScoringAuditLog

logger = logging.getLogger(__name__)

ICD10_CSV = Path(__file__).resolve().parent.parent.parent / "data" / "ICD10codes.csv"

WEIGHTS = {
    "condition": 30,
    "age": 20,
    "sex": 15,
    "geography": 15,
    "health": 20,
}

CONDITION_ICD10_HINTS = {
    "diabetes mellitus": ["E08", "E09", "E10", "E11", "E13"],
    "diabetes": ["E08", "E09", "E10", "E11", "E13"],
    "copd": ["J44"],
    "chronic obstructive pulmonary disease": ["J44"],
    "asthma": ["J45"],
    "arthritis": ["M05", "M06", "M13", "M15", "M16", "M17", "M19"],
    "rheumatoid arthritis": ["M05", "M06"],
    "osteoarthritis": ["M15", "M16", "M17", "M19"],
    "skin cancer": ["C43", "C44"],
    "melanoma": ["C43"],
    "chronic kidney disease": ["N18"],
    "major depressive disorder": ["F32", "F33"],
    "depression": ["F32", "F33"],
    "myocardial infarction": ["I21", "I22"],
    "heart attack": ["I21", "I22"],
    "angina pectoris": ["I20"],
    "angina": ["I20"],
    "stroke": ["I60", "I61", "I63", "I64"],
    "cerebrovascular accident": ["I60", "I61", "I63", "I64"],
    "hypertension": ["I10", "I11", "I12", "I13", "I15"],
    "heart failure": ["I50"],
    "atrial fibrillation": ["I48"],
    "obesity": ["E66"],
    "type 2 diabetes": ["E11"],
    "type 1 diabetes": ["E10"],
}

_EXCLUSION_HEADER_RE = re.compile(r"Exclusion\s+Criteria\s*:", re.IGNORECASE)
_INCLUSION_HEADER_RE = re.compile(r"Inclusion\s+Criteria\s*:", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*[\*\-\u2022]\s*", re.MULTILINE)

HEALTH_SCORES = {
    "excellent": 1.0,
    "very good": 0.85,
    "good": 0.7,
    "fair": 0.45,
    "poor": 0.2,
}

KNOWN_EXCLUSION_TERMS = [
    "diabetes", "copd", "asthma", "arthritis", "cancer", "kidney disease",
    "depressive disorder", "depression", "myocardial infarction", "heart attack",
    "angina", "stroke", "hypertension", "hiv", "aids", "hepatitis",
    "tuberculosis", "pregnancy", "pregnant", "epilepsy", "seizure",
    "liver disease", "renal failure", "heart failure", "dementia",
    "alzheimer", "parkinson", "schizophrenia", "bipolar", "obesity",
    "malignancy", "immunodeficiency", "transplant",
]


class ICD10Mapper:
    """Singleton that loads ICD-10 codes from CSV and maps condition names to code sets."""

    _instance = None
    _loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not ICD10Mapper._loaded:
            self._group_to_codes: dict[str, set[str]] = {}
            self._code_to_description: dict[str, str] = {}
            self._load()
            ICD10Mapper._loaded = True

    def _load(self):
        if not ICD10_CSV.exists():
            logger.warning("ICD-10 CSV not found at %s", ICD10_CSV)
            return

        with open(ICD10_CSV, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 6:
                    continue
                code = row[2].strip().upper()
                desc = row[3].strip()
                group = row[5].strip().lower()

                self._code_to_description[code] = desc
                self._group_to_codes.setdefault(group, set()).add(code)

        logger.info(
            "ICD-10 mapper loaded: %d codes, %d groups",
            len(self._code_to_description),
            len(self._group_to_codes),
        )

    def get_codes_for_condition(self, condition: str) -> set[str]:
        condition_lower = condition.lower().strip()

        for hint_key, prefixes in CONDITION_ICD10_HINTS.items():
            if hint_key in condition_lower or condition_lower in hint_key:
                codes: set[str] = set()
                for prefix in prefixes:
                    prefix_upper = prefix.upper()
                    for code in self._code_to_description:
                        if code.startswith(prefix_upper):
                            codes.add(code)
                if codes:
                    return codes

        matched: set[str] = set()
        for group, codes in self._group_to_codes.items():
            if condition_lower in group or group in condition_lower:
                matched.update(codes)
        if matched:
            return matched

        words = condition_lower.split()
        if words:
            for code, desc in self._code_to_description.items():
                if all(w in desc.lower() for w in words):
                    matched.add(code)

        return matched

    @staticmethod
    def normalize_code(code: str) -> str:
        return code.replace(".", "").replace("-", "").upper().strip()

    def patient_has_code_overlap(
        self, patient_codes: list, trial_codes: set[str]
    ) -> tuple[int, list[str]]:
        if not patient_codes or not trial_codes:
            return 0, []

        trial_prefixes = {c[:3] for c in trial_codes}
        matched = []

        for pc in patient_codes:
            normalized = self.normalize_code(str(pc))
            if normalized in trial_codes or normalized[:3] in trial_prefixes:
                matched.append(normalized)

        return len(matched), matched


def parse_eligibility_criteria(eligibility_text: str) -> dict:
    result = {
        "inclusion_rules": [],
        "exclusion_rules": [],
        "excluded_conditions": [],
    }

    if not eligibility_text:
        return result

    exclusion_match = _EXCLUSION_HEADER_RE.search(eligibility_text)
    inclusion_match = _INCLUSION_HEADER_RE.search(eligibility_text)

    inclusion_text = ""
    exclusion_text = ""

    if inclusion_match and exclusion_match:
        if inclusion_match.start() < exclusion_match.start():
            inclusion_text = eligibility_text[inclusion_match.end():exclusion_match.start()]
            exclusion_text = eligibility_text[exclusion_match.end():]
        else:
            exclusion_text = eligibility_text[exclusion_match.end():inclusion_match.start()]
            inclusion_text = eligibility_text[inclusion_match.end():]
    elif inclusion_match:
        inclusion_text = eligibility_text[inclusion_match.end():]
    elif exclusion_match:
        exclusion_text = eligibility_text[exclusion_match.end():]

    for line in inclusion_text.strip().split("\n"):
        line = _BULLET_RE.sub("", line).strip()
        if line and len(line) > 3:
            result["inclusion_rules"].append(line)

    for line in exclusion_text.strip().split("\n"):
        line = _BULLET_RE.sub("", line).strip()
        if line and len(line) > 3:
            result["exclusion_rules"].append(line)

    for rule in result["exclusion_rules"]:
        rule_lower = rule.lower()
        for term in KNOWN_EXCLUSION_TERMS:
            if term in rule_lower:
                result["excluded_conditions"].append(term)

    return result


class ScoringAgent:
    """Scores and ranks orchestrator-matched patients by relevance to a trial.

    Pipeline:
    1. Fetch trial -> extract structured criteria
    2. Get matched patients from orchestrator (or accept pre-filtered list)
    3. Parse eligibilityCriteria into inclusion/exclusion rules
    4. Map trial conditions -> ICD-10 codes via CSV
    5. Score each patient 0-100 across five weighted dimensions
    6. Apply exclusion criteria (disqualified patients get score 0)
    7. Return ranked list with per-factor breakdown
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.icd10_mapper = ICD10Mapper()
        self.orchestrator = TrialMatchOrchestrator(session)

    async def fetch_trial(self, trial_id: str) -> dict | None:
        return await self.orchestrator.fetch_trial(trial_id)

    async def fetch_patient_details(
        self, patient_ids: list[str], source: str = "kaggle",
    ) -> dict[str, dict]:
        if not patient_ids:
            return {}

        if source == "fhir":
            return await self._fetch_fhir_patient_details(patient_ids)

        # ── Kaggle path (unchanged) ──────────────────────────────────
        placeholders = ", ".join(f":id_{i}" for i in range(len(patient_ids)))
        params = {f"id_{i}": pid for i, pid in enumerate(patient_ids)}

        result = await self.session.execute(
            text(f"""
                SELECT id::text, icd10_codes, conditions, metadata
                FROM patients
                WHERE id::text IN ({placeholders})
            """),
            params,
        )

        data = {}
        for row in result.fetchall():
            data[str(row[0])] = {
                "icd10_codes": row[1] or [],
                "conditions": row[2] or [],
                "metadata": row[3] or {},
            }
        return data

    async def _fetch_fhir_patient_details(self, patient_ids: list[str]) -> dict[str, dict]:
        """Fetch enrichment data for scoring from FHIR tables.

        Pulls ICD-10 codes and condition names from fhir_conditions,
        which the Kaggle path gets from JSONB columns on the patients table.
        """
        if not patient_ids:
            return {}

        placeholders = ", ".join(f":id_{i}" for i in range(len(patient_ids)))
        params = {f"id_{i}": pid for i, pid in enumerate(patient_ids)}

        result = await self.session.execute(
            text(f"""
                SELECT
                    fp.id::text AS patient_id,
                    array_agg(DISTINCT fc.icd10_code) FILTER (WHERE fc.icd10_code IS NOT NULL) AS icd10_codes,
                    array_agg(DISTINCT fc.snomed_code) FILTER (WHERE fc.snomed_code IS NOT NULL) AS snomed_codes,
                    array_agg(DISTINCT fc.display_name) FILTER (WHERE fc.display_name IS NOT NULL) AS conditions
                FROM fhir_patients fp
                LEFT JOIN fhir_conditions fc ON fc.patient_id = fp.id
                WHERE fp.id::text IN ({placeholders})
                GROUP BY fp.id
            """),
            params,
        )

        data = {}
        for row in result.fetchall():
            data[str(row[0])] = {
                "icd10_codes": row[1] or [],
                "snomed_codes": row[2] or [],
                "conditions": row[3] or [],
                "metadata": {},
            }
        return data

    def _score_conditions(
        self,
        patient: dict,
        patient_db: dict,
        trial_conditions: list[str],
        trial_icd10_codes: set[str],
    ) -> dict:
        max_pts = WEIGHTS["condition"]
        patient_conditions = [c.lower() for c in (patient.get("conditions") or [])]
        patient_icd = patient_db.get("icd10_codes", [])
        trial_conds_lower = [c.lower() for c in trial_conditions]

        if not trial_conds_lower:
            return {"score": max_pts, "max": max_pts, "details": "No trial conditions — full score"}

        condition_matches = []
        for tc in trial_conds_lower:
            for pc in patient_conditions:
                if tc in pc or pc in tc:
                    condition_matches.append(pc)
                    break

        cond_ratio = len(condition_matches) / len(trial_conds_lower)

        icd_count, icd_matches = self.icd10_mapper.patient_has_code_overlap(
            patient_icd, trial_icd10_codes
        )
        icd_ratio = min(icd_count / max(len(trial_icd10_codes), 1), 1.0) if trial_icd10_codes else 0

        combined = (0.7 * cond_ratio + 0.3 * icd_ratio) if trial_icd10_codes else cond_ratio
        score = round(combined * max_pts, 2)

        parts = []
        if condition_matches:
            parts.append(f"Matched: {', '.join(condition_matches)}")
        else:
            parts.append("No direct condition matches")
        if icd_matches:
            parts.append(f"ICD-10 overlaps: {len(icd_matches)}")
        parts.append(f"{len(condition_matches)}/{len(trial_conds_lower)} conditions")

        return {"score": score, "max": max_pts, "details": "; ".join(parts)}

    def _score_age(self, patient: dict, min_age: int | None, max_age: int | None) -> dict:
        max_pts = WEIGHTS["age"]
        age = patient.get("age")

        if age is None:
            return {"score": round(max_pts * 0.5, 2), "max": max_pts, "details": "Age unknown — partial score"}

        if min_age is None and max_age is None:
            return {"score": max_pts, "max": max_pts, "details": f"No age restriction; patient age {age}"}

        in_range = True
        if min_age is not None and age < min_age:
            in_range = False
        if max_age is not None and age > max_age:
            in_range = False

        range_str = f"{min_age or '?'}-{max_age or '?'}"

        if in_range:
            if min_age is not None and max_age is not None and max_age > min_age:
                center = (min_age + max_age) / 2
                half_range = (max_age - min_age) / 2
                dist = abs(age - center) / half_range
                centrality = 1.0 - dist * 0.15
                score = round(max_pts * centrality, 2)
            else:
                score = max_pts
            return {"score": score, "max": max_pts, "details": f"Age {age} within range {range_str}"}

        gap = 0
        if min_age is not None and age < min_age:
            gap = min_age - age
        elif max_age is not None and age > max_age:
            gap = age - max_age
        penalty = min(gap / 10.0, 1.0)
        score = round(max_pts * max(0, 1 - penalty), 2)
        return {"score": score, "max": max_pts, "details": f"Age {age} outside range {range_str} (gap {gap} yrs)"}

    def _score_sex(self, patient: dict, trial_sex: str) -> dict:
        max_pts = WEIGHTS["sex"]

        if not trial_sex or trial_sex.upper() == "ALL":
            return {"score": max_pts, "max": max_pts, "details": "Trial accepts all sexes"}

        p_gender = (patient.get("gender") or "").lower()
        t_sex = trial_sex.lower()

        if not p_gender:
            return {"score": round(max_pts * 0.5, 2), "max": max_pts, "details": "Patient sex unknown"}

        if p_gender == t_sex or t_sex in p_gender:
            return {"score": max_pts, "max": max_pts, "details": f"Sex match: {p_gender}"}

        return {"score": 0, "max": max_pts, "details": f"Sex mismatch: patient={p_gender}, trial={trial_sex}"}

    def _score_geography(
        self, patient: dict, location_countries: list[str], location_cities: list[str]
    ) -> dict:
        max_pts = WEIGHTS["geography"]

        if not location_countries and not location_cities:
            return {"score": max_pts, "max": max_pts, "details": "No location restriction"}

        p_country = (patient.get("country") or "").lower()
        p_state = (patient.get("state") or "").lower()

        if not p_country:
            return {"score": round(max_pts * 0.3, 2), "max": max_pts, "details": "Patient location unknown"}

        countries_l = [c.lower() for c in location_countries]
        cities_l = [c.lower() for c in location_cities]

        country_match = any(p_country in c or c in p_country for c in countries_l)
        city_match = any(p_state in c or c in p_state for c in cities_l) if cities_l else False

        if country_match and city_match:
            return {"score": max_pts, "max": max_pts, "details": f"Country + state match ({p_country}, {p_state})"}
        if country_match:
            return {"score": round(max_pts * 0.75, 2), "max": max_pts, "details": f"Country match ({p_country})"}

        score = round(max_pts * 0.15, 2)
        return {"score": score, "max": max_pts, "details": f"Different country: {p_country} vs {', '.join(location_countries[:3])}"}

    def _score_health(self, patient: dict, patient_db: dict) -> dict:
        max_pts = WEIGHTS["health"]
        parts = []

        bmi = patient.get("bmi")
        if bmi is not None:
            if 18.5 <= bmi <= 24.9:
                bmi_s = 7.0; parts.append(f"BMI {bmi:.1f} (normal)")
            elif 25.0 <= bmi <= 29.9:
                bmi_s = 5.0; parts.append(f"BMI {bmi:.1f} (overweight)")
            elif 15.0 <= bmi < 18.5:
                bmi_s = 4.0; parts.append(f"BMI {bmi:.1f} (underweight)")
            elif 30.0 <= bmi <= 34.9:
                bmi_s = 3.0; parts.append(f"BMI {bmi:.1f} (obese I)")
            else:
                bmi_s = 1.0; parts.append(f"BMI {bmi:.1f} (extreme)")
        else:
            bmi_s = 3.5; parts.append("BMI unknown")

        smoker = (patient.get("smoker_status") or "").lower()
        if "never" in smoker:
            smoke_s = 7.0; parts.append("Never smoked")
        elif "former" in smoker or "ex" in smoker:
            smoke_s = 4.5; parts.append("Former smoker")
        elif "current" in smoker or "yes" in smoker:
            smoke_s = 2.0; parts.append("Current smoker")
        else:
            smoke_s = 3.5; parts.append(f"Smoker: {smoker or 'unknown'}")

        health = (patient.get("general_health") or "").lower()
        health_ratio = HEALTH_SCORES.get(health, 0.5)
        health_s = round(6.0 * health_ratio, 2)
        parts.append(f"Health: {health or 'unknown'}")

        total = round(min(bmi_s + smoke_s + health_s, max_pts), 2)
        return {"score": total, "max": max_pts, "details": "; ".join(parts)}

    def _check_exclusions(
        self, patient: dict, patient_db: dict, parsed: dict,
        trial_conditions: list[str] | None = None,
    ) -> tuple[bool, list[str]]:
        excluded_terms = parsed.get("excluded_conditions", [])
        if not excluded_terms:
            return False, []

        # Don't exclude patients for having the trial's own target conditions
        trial_conds_lower = {c.lower() for c in (trial_conditions or [])}

        patient_conds = [c.lower() for c in (patient.get("conditions") or [])]
        reasons = []
        for term in excluded_terms:
            if term in trial_conds_lower:
                continue
            for pc in patient_conds:
                if term in pc or pc in term:
                    reasons.append(f"Has excluded condition '{pc}' (rule: {term})")
        return bool(reasons), reasons

    def score_patient(
        self,
        patient: dict,
        patient_db: dict,
        criteria: dict,
        parsed: dict,
        trial_icd10: set[str],
    ) -> dict:
        excluded, reasons = self._check_exclusions(
            patient, patient_db, parsed, trial_conditions=criteria["conditions"]
        )

        cond = self._score_conditions(patient, patient_db, criteria["conditions"], trial_icd10)
        age = self._score_age(patient, criteria["min_age"], criteria["max_age"])
        sex = self._score_sex(patient, criteria["sex"])
        geo = self._score_geography(
            patient,
            criteria.get("location_countries", []),
            criteria.get("location_cities", []),
        )
        health = self._score_health(patient, patient_db)

        composite = round(cond["score"] + age["score"] + sex["score"] + geo["score"] + health["score"], 2)
        if excluded:
            composite = 0.0

        return {
            "patient_id": patient["id"],
            "display_patient_id": patient.get("display_patient_id"),
            "composite_score": composite,
            "excluded": excluded,
            "exclusion_reasons": reasons,
            "patient_summary": {
                "age": patient.get("age"),
                "gender": patient.get("gender"),
                "conditions": patient.get("conditions"),
                "state": patient.get("state"),
                "country": patient.get("country"),
                "bmi": patient.get("bmi"),
                "smoker_status": patient.get("smoker_status"),
                "general_health": patient.get("general_health"),
            },
            "breakdown": {
                "condition": cond,
                "age": age,
                "sex": sex,
                "geography": geo,
                "health": health,
            },
        }

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
        """Score patients matched via free-text criteria (no trial lookup).

        Uses LLM extraction for structured keywords, then orchestrator
        for matching, then runs the same scoring pipeline.
        """
        pipeline_start = time.perf_counter()

        # LLM extraction + matching via orchestrator
        t2 = time.perf_counter()
        try:
            extracted = await self.orchestrator.extract_criteria_from_text(search_query)
            llm_query = extracted.get("search_query", "").strip()
        except Exception as e:
            logger.warning("LLM criteria extraction failed in scoring: %s", e)
            extracted = {}
            llm_query = ""

        effective_sex = sex if sex != "ALL" else extracted.get("sex", "ALL")
        effective_min_age = min_age if min_age is not None else extracted.get("min_age")
        effective_max_age = max_age if max_age is not None else extracted.get("max_age")
        effective_min_bmi = min_bmi if min_bmi is not None else extracted.get("min_bmi")
        effective_max_bmi = max_bmi if max_bmi is not None else extracted.get("max_bmi")
        effective_smoker = smoker_status if smoker_status is not None else extracted.get("smoker_status")

        has_demographic_filters = any([
            effective_sex != "ALL", effective_min_age, effective_max_age,
            effective_min_bmi, effective_max_bmi, effective_smoker,
        ])
        if llm_query:
            effective_query = llm_query
        elif has_demographic_filters and source == "fhir":
            effective_query = ""
        else:
            effective_query = search_query

        patients, patient_ids = await self.orchestrator.match_patients(
            search_query=effective_query,
            sex=effective_sex,
            min_age=effective_min_age,
            max_age=effective_max_age,
            min_bmi=effective_min_bmi,
            max_bmi=effective_max_bmi,
            smoker_status=effective_smoker,
            limit=limit,
            source=source,
        )
        stage2_ms = int((time.perf_counter() - t2) * 1000)

        pipeline_info = {
            "text_to_sql_prefiltered": 0,
            "text_to_sql_query": None,
            "root_word_verified": len(patients),
            "used_prefilter": False,
            "cache_hit": False,
            "stage1_ms": 0,
            "stage2_ms": stage2_ms,
        }

        # Build a criteria dict compatible with score_patient
        criteria = {
            "conditions": [t.strip() for t in effective_query.split(" OR ") if t.strip()],
            "keywords": [],
            "search_query": effective_query,
            "sex": effective_sex,
            "min_age": effective_min_age,
            "max_age": effective_max_age,
            "eligibility_text": "",
            "location_countries": [],
            "location_cities": [],
        }

        # Stage 3: Scoring
        t3 = time.perf_counter()
        parsed = parse_eligibility_criteria("")

        trial_icd10: set[str] = set()
        for cond in criteria["conditions"]:
            trial_icd10.update(self.icd10_mapper.get_codes_for_condition(cond))

        patient_db_data = await self.fetch_patient_details(patient_ids, source=source)

        scored = []
        for p in patients:
            db = patient_db_data.get(p["id"], {"icd10_codes": [], "conditions": [], "metadata": {}})
            scored.append(self.score_patient(p, db, criteria, parsed, trial_icd10))

        scored.sort(key=lambda x: (not x["excluded"], x["composite_score"]), reverse=True)
        stage3_ms = int((time.perf_counter() - t3) * 1000)

        pipeline_info["stage3_ms"] = stage3_ms
        pipeline_info["total_ms"] = int((time.perf_counter() - pipeline_start) * 1000)

        eligible = [s for s in scored if not s["excluded"]]
        excluded = [s for s in scored if s["excluded"]]
        eligible_scores = [s["composite_score"] for s in eligible]

        result = {
            "trial_id": "manual",
            "trial_nct_id": None,
            "trial_title": "Manual criteria search",
            "trial_status": None,
            "criteria_used": {
                "conditions": criteria["conditions"],
                "keywords": [],
                "search_query": effective_query,
                "sex_filter": effective_sex,
                "age_range": {"min": effective_min_age, "max": effective_max_age},
                "eligibility_text": search_query,
                "location_countries": [],
                "location_cities": [],
            },
            "llm_extraction": extracted if extracted else None,
            "pipeline": pipeline_info,
            "parsed_eligibility": parsed,
            "icd10_codes_mapped": len(trial_icd10),
            "scoring_weights": WEIGHTS,
            "summary": {
                "total_scored": len(scored),
                "eligible_count": len(eligible),
                "excluded_count": len(excluded),
                "avg_score": round(sum(eligible_scores) / len(eligible_scores), 2) if eligible_scores else 0,
                "max_score": max(eligible_scores) if eligible_scores else 0,
                "min_score": min(eligible_scores) if eligible_scores else 0,
            },
            "scored_patients": scored,
        }

        audit_id = await self._persist_audit_log(result, triggered_by="manual_criteria")
        result["audit_log_id"] = audit_id
        return result

    async def _persist_audit_log(
        self,
        result: dict,
        triggered_by: str | None = None,
    ) -> str:
        """Write a scoring run as an immutable row in scoring_audit_log.

        Returns the UUID of the inserted audit record (str).
        """
        audit_id = uuid4()
        entry = ScoringAuditLog(
            id=audit_id,
            trial_id=result.get("trial_id"),
            trial_nct_id=result.get("trial_nct_id"),
            trial_title=result.get("trial_title"),
            trial_status=result.get("trial_status"),
            triggered_by=triggered_by,
            run_at=datetime.now(timezone.utc),
            criteria_used=result.get("criteria_used", {}),
            pipeline_info=result.get("pipeline", {}),
            parsed_eligibility=result.get("parsed_eligibility", {}),
            icd10_codes_mapped=result.get("icd10_codes_mapped", 0),
            scoring_weights=result.get("scoring_weights", {}),
            summary=result.get("summary", {}),
            scored_patients=result.get("scored_patients", []),
        )
        self.session.add(entry)
        await self.session.flush()
        audit_id_str = str(audit_id)
        logger.info(
            "Scoring audit log persisted",
            extra={"audit_id": audit_id_str, "trial_nct_id": result.get("trial_nct_id")},
        )
        return audit_id_str

    async def run(
        self,
        trial_id: str,
        limit: int = 200,
        pre_filtered_patients: list[dict] | None = None,
        triggered_by: str | None = None,
        source: str = "kaggle",
    ) -> dict:
        pipeline_start = time.perf_counter()

        trial = await self.fetch_trial(trial_id)
        if not trial:
            raise ValueError(f"Trial not found: {trial_id}")

        criteria = self.orchestrator.extract_criteria(trial)

        if pre_filtered_patients is not None:
            patients = pre_filtered_patients
            patient_ids = [p["id"] for p in patients]
            pipeline_info = {
                "text_to_sql_prefiltered": 0, "text_to_sql_query": None,
                "root_word_verified": len(patients), "used_prefilter": False,
                "cache_hit": False, "stage1_ms": 0, "stage2_ms": 0,
            }
        else:
            if not criteria["search_query"]:
                raise ValueError("Trial has no conditions or keywords to match against")

            # Stage 1: Text-to-SQL pre-filter (DB-backed cache via orchestrator)
            t1 = time.perf_counter()
            prefiltered_ids = []
            generated_sql = None
            cache_hit = False

            cache_key = f"{trial_id}:{source}" if source != "kaggle" else trial_id
            cached = await self.orchestrator.pipeline_cache.get(cache_key)
            if cached:
                generated_sql = cached["generated_sql"]
                prefiltered_ids = cached["patient_ids"]
                cache_hit = True
            else:
                try:
                    generated_sql, prefiltered_ids = await self.orchestrator.text_to_sql.generate_patient_filter_sql(
                        criteria, source=source,
                    )
                    await self.orchestrator.pipeline_cache.set(cache_key, generated_sql, prefiltered_ids)
                except Exception as e:
                    logger.warning("Text-to-SQL pre-filter failed in scoring: %s", e)

            stage1_ms = int((time.perf_counter() - t1) * 1000)
            used_prefilter = bool(prefiltered_ids)

            # Stage 2: Root Word Search (or FHIR condition search)
            t2 = time.perf_counter()
            patients, patient_ids = await self.orchestrator.match_patients(
                search_query=criteria["search_query"],
                sex=criteria["sex"],
                min_age=criteria["min_age"],
                max_age=criteria["max_age"],
                limit=limit,
                prefilter_patient_ids=prefiltered_ids if prefiltered_ids else None,
                source=source,
            )

            if used_prefilter and not patients:
                patients, patient_ids = await self.orchestrator.match_patients(
                    search_query=criteria["search_query"],
                    sex=criteria["sex"],
                    min_age=criteria["min_age"],
                    max_age=criteria["max_age"],
                    limit=limit,
                    source=source,
                )
                used_prefilter = False
            stage2_ms = int((time.perf_counter() - t2) * 1000)

            pipeline_info = {
                "text_to_sql_prefiltered": len(prefiltered_ids),
                "text_to_sql_query": generated_sql,
                "root_word_verified": len(patients),
                "used_prefilter": used_prefilter,
                "cache_hit": cache_hit,
                "stage1_ms": stage1_ms,
                "stage2_ms": stage2_ms,
            }

        # Stage 3: Scoring
        t3 = time.perf_counter()
        parsed = parse_eligibility_criteria(criteria.get("eligibility_text", ""))

        trial_icd10: set[str] = set()
        for cond in criteria["conditions"]:
            trial_icd10.update(self.icd10_mapper.get_codes_for_condition(cond))

        patient_db_data = await self.fetch_patient_details(patient_ids, source=source)

        scored = []
        for p in patients:
            db = patient_db_data.get(p["id"], {"icd10_codes": [], "conditions": [], "metadata": {}})
            scored.append(self.score_patient(p, db, criteria, parsed, trial_icd10))

        scored.sort(key=lambda x: (not x["excluded"], x["composite_score"]), reverse=True)
        stage3_ms = int((time.perf_counter() - t3) * 1000)

        pipeline_info["stage3_ms"] = stage3_ms
        pipeline_info["total_ms"] = int((time.perf_counter() - pipeline_start) * 1000)

        eligible = [s for s in scored if not s["excluded"]]
        excluded = [s for s in scored if s["excluded"]]
        eligible_scores = [s["composite_score"] for s in eligible]

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
                "age_range": {"min": criteria["min_age"], "max": criteria["max_age"]},
                "eligibility_text": (criteria["eligibility_text"] or "")[:1000],
                "location_countries": criteria.get("location_countries", []),
                "location_cities": criteria.get("location_cities", []),
            },
            "pipeline": pipeline_info,
            "parsed_eligibility": parsed,
            "icd10_codes_mapped": len(trial_icd10),
            "scoring_weights": WEIGHTS,
            "summary": {
                "total_scored": len(scored),
                "eligible_count": len(eligible),
                "excluded_count": len(excluded),
                "avg_score": round(sum(eligible_scores) / len(eligible_scores), 2) if eligible_scores else 0,
                "max_score": max(eligible_scores) if eligible_scores else 0,
                "min_score": min(eligible_scores) if eligible_scores else 0,
            },
            "scored_patients": scored,
        }

        audit_id = await self._persist_audit_log(result, triggered_by=triggered_by)
        result["audit_log_id"] = audit_id
        return result
