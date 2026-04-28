import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "agent_results"

DEMOGRAPHIC_FIELDS = """
    p.id,
    p.display_patient_id,
    p.age,
    p.gender,
    p.ethnicity,
    p.geography->>'state' AS state,
    p.geography->>'country' AS country,
    p.conditions,
    p.metadata->>'bmi' AS bmi,
    p.metadata->>'smokerStatus' AS smoker_status,
    p.metadata->>'generalHealth' AS general_health
"""

_TSVECTOR_EXPR = """to_tsvector('english',
    coalesce(p.conditions::text, '') || ' ' ||
    coalesce(p.icd10_codes::text, '') || ' ' ||
    coalesce(p.metadata::text, '') || ' ' ||
    coalesce(p.trial_preferences::text, '') || ' ' ||
    coalesce(p.gender, '') || ' ' ||
    coalesce(p.ethnicity, '') || ' ' ||
    coalesce(p.geography::text, '')
)"""

_TSQUERY_FN_MAP = {
    "websearch": "websearch_to_tsquery",
    "plain": "plainto_tsquery",
    "phrase": "phraseto_tsquery",
}


class RootWordSearchAgent:
    """Pre-filters the patient dataset using PostgreSQL tsvector stemming.

    Purpose: Take a search query like "diabetes cardiac", extract root words
    (diabet, cardiac), search patient JSONB data (conditions, icd10_codes)
    using those stems, and return ONLY the matching patient IDs + demographics.
    Everything else is discarded.

    This filtered set then goes forward to Agent 1 or a report pipeline.
    The full 700+ patient pool gets shortened to just the relevant subset.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def extract_root_words(self, query: str) -> list[dict]:
        """Use PostgreSQL's ts_debug to break a query into root words.

        "diabetes cardiac" → diabet, cardiac
        "hypertensive patients" → hypertens, patient
        """
        result = await self.session.execute(
            text("SELECT alias, token, lexemes FROM ts_debug('english', :q)"),
            {"q": query},
        )
        rows = result.fetchall()

        root_words = []
        for alias, token, lexemes in rows:
            if lexemes:
                root_words.append({
                    "type": alias,
                    "original": token,
                    "root_words": list(lexemes),
                })
        return root_words

    async def get_total_patient_count(self) -> int:
        """Get total patients in DB — shows how much the dataset was shortened."""
        result = await self.session.execute(text("SELECT COUNT(*) FROM patients"))
        return result.scalar()

    async def search_patients(
        self,
        query: str,
        mode: str = "websearch",
        limit: int = 100,
    ) -> dict:
        """Core search: find patients whose conditions/codes match the query's root words.

        How it works:
        1. JSONB columns (conditions, icd10_codes, metadata) are cast to text via ::text
        2. Multiple columns are concatenated with || so one tsvector covers all patient data
        3. PostgreSQL stems both the query and the concatenated text
        4. Matching patients are returned with ONLY demographics (not full records)
        5. Results ranked by ts_rank (most relevant first)
        """
        tsquery_fn = _TSQUERY_FN_MAP.get(mode, "websearch_to_tsquery")

        sql = f"""
            SELECT
                {DEMOGRAPHIC_FIELDS},
                ts_rank({_TSVECTOR_EXPR}, query) AS relevance_score
            FROM patients p,
                 {tsquery_fn}('english', :query) AS query
            WHERE {_TSVECTOR_EXPR} @@ query
            ORDER BY relevance_score DESC
            LIMIT :limit
        """

        logger.info("Patient root-word search", extra={"query": query, "mode": mode})
        result = await self.session.execute(text(sql), {"query": query, "limit": limit})
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

    def _save_results(self, result: dict) -> str:
        """Save search results to a JSON file in agent_results/ folder.

        Filename format: rootword_<query>_<timestamp>.json
        Returns the saved file path.
        """
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        safe_query = "".join(c if c.isalnum() or c == " " else "" for c in result["query"])
        safe_query = safe_query.strip().replace(" ", "_")[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rootword_{safe_query}_{timestamp}.json"
        filepath = RESULTS_DIR / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)

        logger.info("Results saved", extra={"file": str(filepath)})
        return str(filepath)

    async def run(
        self,
        query: str,
        mode: str = "websearch",
        limit: int = 100,
    ) -> dict:
        """Full pipeline: extract roots + count + search in minimal roundtrips."""
        tsquery_fn = _TSQUERY_FN_MAP.get(mode, "websearch_to_tsquery")

        combined_sql = text(f"""
            WITH root AS (
                SELECT alias, token, lexemes FROM ts_debug('english', :query)
            ),
            cnt AS (
                SELECT COUNT(*) AS total FROM patients
            ),
            matched AS (
                SELECT
                    {DEMOGRAPHIC_FIELDS},
                    ts_rank({_TSVECTOR_EXPR}, q) AS relevance_score
                FROM patients p,
                     {tsquery_fn}('english', :query) AS q
                WHERE {_TSVECTOR_EXPR} @@ q
                ORDER BY relevance_score DESC
                LIMIT :limit
            )
            SELECT 'root' AS _src, alias, token, lexemes::text,
                   NULL::uuid AS id, NULL AS display_patient_id,
                   NULL::int AS age, NULL AS gender, NULL AS ethnicity,
                   NULL AS state, NULL AS country, NULL::jsonb AS conditions,
                   NULL AS bmi, NULL AS smoker_status, NULL AS general_health,
                   NULL::float AS relevance_score, NULL::bigint AS total
            FROM root
            UNION ALL
            SELECT 'cnt', NULL, NULL, NULL,
                   NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL, NULL, total
            FROM cnt
            UNION ALL
            SELECT 'match', NULL, NULL, NULL,
                   id, display_patient_id, age, gender, ethnicity,
                   state, country, conditions,
                   bmi, smoker_status, general_health,
                   relevance_score, NULL
            FROM matched
        """)

        result = await self.session.execute(combined_sql, {"query": query, "limit": limit})
        rows = result.fetchall()

        root_words = []
        total_patients = 0
        patients = []
        patient_ids = []

        for row in rows:
            src = row[0]
            if src == "root" and row[3]:
                root_words.append({
                    "type": row[1],
                    "original": row[2],
                    "root_words": row[3].strip("{}").split(",") if row[3] else [],
                })
            elif src == "cnt":
                total_patients = row[-1] or 0
            elif src == "match":
                pid = str(row[4])
                patient_ids.append(pid)
                patients.append({
                    "id": pid,
                    "display_patient_id": row[5],
                    "age": row[6],
                    "gender": row[7],
                    "ethnicity": row[8],
                    "state": row[9],
                    "country": row[10],
                    "conditions": row[11],
                    "bmi": float(row[12]) if row[12] else None,
                    "smoker_status": row[13],
                    "general_health": row[14],
                    "relevance_score": float(row[15]) if row[15] else 0.0,
                })

        return {
            "query": query,
            "mode": mode,
            "root_words": root_words,
            "total_patients": total_patients,
            "filtered_count": len(patients),
            "filtered_patient_ids": patient_ids,
            "patients": patients,
        }
