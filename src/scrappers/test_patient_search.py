"""
Example usage of the patient search helper function using ts_vector indexes.

Run from project root:
    uv run python -m src.scrappers.test_patient_search
"""

from __future__ import annotations

import asyncio
import logging

from src.db.models.patient import search_patients_by_conditions
from src.db.session import AsyncSessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def demo_search() -> None:
    """Demonstrate various search patterns using the ts_vector indexes."""

    async with AsyncSessionLocal() as session:
        logger.info("=== Testing Patient Search with ts_vector Indexes ===\n")

        # Test 1: Natural language search for conditions
        logger.info("Test 1: Natural language - 'diabetes cardiac'")
        logger.info("  (Searches BOTH conditions and icd10_codes columns)")
        patients = await search_patients_by_conditions(session, "diabetes cardiac")
        logger.info(f"Found {len(patients)} patients")
        for p in patients[:3]:
            logger.info(
                f"  - {p.display_patient_id}: {p.conditions} | ICD10: {p.icd10_codes}"
            )

        # Test 2: ICD-10 code search
        logger.info("\nTest 2: ICD-10 codes only - 'E11 I20'")
        logger.info("  (Searches BOTH conditions and icd10_codes columns)")
        patients = await search_patients_by_conditions(session, "E11 I20")
        logger.info(f"Found {len(patients)} patients")
        for p in patients[:3]:
            logger.info(
                f"  - {p.display_patient_id}: {p.conditions} | ICD10: {p.icd10_codes}"
            )

        # Test 3: Mixed search - condition names + ICD codes
        logger.info("\nTest 3: COMBINED - 'diabetes E11 cardiac I20'")
        logger.info("  (Demonstrates unified search across both columns)")
        patients = await search_patients_by_conditions(session, "diabetes E11 cardiac I20")
        logger.info(f"Found {len(patients)} patients")
        for p in patients[:3]:
            logger.info(
                f"  - {p.display_patient_id}: {p.conditions} | ICD10: {p.icd10_codes}"
            )

        # Test 4: Boolean operators
        logger.info("\nTest 4: Boolean operators - 'diabetes OR asthma'")
        logger.info("  (Finds patients with either condition)")
        patients = await search_patients_by_conditions(session, "diabetes OR asthma")
        logger.info(f"Found {len(patients)} patients")
        for p in patients[:3]:
            logger.info(
                f"  - {p.display_patient_id}: {p.conditions} | ICD10: {p.icd10_codes}"
            )

        # Test 5: Exclusion search
        logger.info("\nTest 5: Exclusion - 'diabetes -cardiac'")
        logger.info("  (Finds diabetes patients WITHOUT cardiac conditions)")
        patients = await search_patients_by_conditions(session, "diabetes -cardiac")
        logger.info(f"Found {len(patients)} patients")
        for p in patients[:3]:
            logger.info(
                f"  - {p.display_patient_id}: {p.conditions} | ICD10: {p.icd10_codes}"
            )

        # Test 6: Phrase search
        logger.info("\nTest 6: Exact phrase - 'Major Depressive Disorder'")
        patients = await search_patients_by_conditions(
            session, "Major Depressive Disorder", mode="phrase"
        )
        logger.info(f"Found {len(patients)} patients")
        for p in patients[:3]:
            logger.info(
                f"  - {p.display_patient_id}: {p.conditions} | ICD10: {p.icd10_codes}"
            )

        # Test 7: Pagination
        logger.info("\nTest 7: Pagination - 'diabetes' (limit 5, offset 5)")
        patients = await search_patients_by_conditions(
            session, "diabetes", limit=5, offset=5
        )
        logger.info(f"Found {len(patients)} patients (page 2)")
        for p in patients:
            logger.info(
                f"  - {p.display_patient_id}: {p.conditions} | ICD10: {p.icd10_codes}"
            )


async def main() -> None:
    try:
        await demo_search()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
