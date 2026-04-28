"""Check which clinical trials have at least one matching patient via tsvector search.

Outputs a JSON file with valid trial IDs (those with >=1 patient match).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:kdf79bsl@ulalo-db.theagentic.ai:5437/postgres",
)

TSVECTOR_EXPR = """
to_tsvector('english',
    coalesce(p.conditions::text, '') || ' ' ||
    coalesce(p.icd10_codes::text, '') || ' ' ||
    coalesce(p.metadata::text, '') || ' ' ||
    coalesce(p.display_patient_id, '')
)
"""

CHECK_PATIENT_SQL = f"""
SELECT COUNT(*) FROM patients p
WHERE {TSVECTOR_EXPR} @@ websearch_to_tsquery('english', $1)
"""

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "valid_trial_ids.json"


async def main():
    conn = await asyncpg.connect(DATABASE_URL)

    try:
        rows = await conn.fetch(
            "SELECT nct_id, title, status, payload FROM clinical_trials WHERE nct_id IS NOT NULL ORDER BY nct_id"
        )
        print(f"Total trials in DB: {len(rows)}")

        total_patients = await conn.fetchval("SELECT COUNT(*) FROM patients")
        print(f"Total patients in DB: {total_patients}")

        valid = []
        no_match = []

        for i, row in enumerate(rows, 1):
            nct_id = row["nct_id"]
            title = row["title"] or "Untitled"
            status = row["status"] or "UNKNOWN"
            payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])

            conditions = payload.get("conditions", [])
            keywords = payload.get("keywords", [])

            search_terms = conditions + keywords
            if not search_terms:
                print(f"  [{i}/{len(rows)}] {nct_id} — SKIP (no conditions/keywords)")
                no_match.append({"nct_id": nct_id, "title": title, "reason": "no_search_terms"})
                continue

            search_query = " OR ".join(search_terms)

            try:
                count = await conn.fetchval(CHECK_PATIENT_SQL, search_query)
            except Exception as e:
                print(f"  [{i}/{len(rows)}] {nct_id} — ERROR: {e}")
                no_match.append({"nct_id": nct_id, "title": title, "reason": f"error: {e}"})
                continue

            if count > 0:
                print(f"  [{i}/{len(rows)}] {nct_id} — {count:>4} patients  ✓  {title[:60]}")
                valid.append({
                    "nct_id": nct_id,
                    "title": title,
                    "status": status,
                    "conditions": conditions,
                    "patient_count": count,
                })
            else:
                print(f"  [{i}/{len(rows)}] {nct_id} —    0 patients  ✗  {title[:60]}")
                no_match.append({"nct_id": nct_id, "title": title, "reason": "no_patients"})

        print(f"\n{'='*60}")
        print(f"RESULTS: {len(valid)} trials with patients / {len(no_match)} without / {len(rows)} total")
        print(f"{'='*60}")

        for v in valid:
            conds = ", ".join(v["conditions"][:3])
            print(f"  ✓ {v['nct_id']}  ({v['patient_count']:>4} patients)  [{v['status']}]  {conds}")

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(valid, f, indent=2)

        print(f"\nSaved to: {OUTPUT_FILE}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
