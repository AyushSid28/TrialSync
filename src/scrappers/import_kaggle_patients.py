"""
Import Kaggle-style patient CSV into PostgreSQL as Patient rows (joined User + patients).

Mirrors SmartPatientMobileApp/backend/scripts/importKagglePatients.js field mapping.
Dataset reference: https://www.kaggle.com/datasets/tarekmuhammed/data-of-patients-for-medical-field

Features:
  - Streaming CSV reader (memory-efficient for large datasets)
  - Concurrent worker pool for fast ingestion (21K+ records)
  - Queue-based distribution (no full file in memory)
  - Connection pooling via AsyncSessionLocal
  - Batch commits for efficiency
  - Progress tracking and statistics

Requires:
  - DATABASE_URL and other settings from .env (see src.core.config)
  - Alembic migration applied (including patient demographics columns)
  - CSV with headers matching the Kaggle CVD dataset (see docs/kaggle-patient-import.md)

Run from project root:

    uv run python -m src.scrappers.import_kaggle_patients --file /path/to/cvd_cleaned.csv --workers 4
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import random
import secrets
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.models.patient import Patient
from src.db.models.user import User
from src.db.session import AsyncSessionLocal, engine

_ = settings  # load .env

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _hash_demo_password() -> str:
    """Bcrypt a random secret (bytes, under 72-byte bcrypt limit). Avoids passlib+bcrypt4 incompat."""
    secret = secrets.token_bytes(32)
    return bcrypt.hashpw(secret, bcrypt.gensalt(rounds=12)).decode("utf-8")


AGE_CATEGORY_MAP: dict[str, int] = {
    "18-24": 21,
    "25-29": 27,
    "30-34": 32,
    "35-39": 37,
    "40-44": 42,
    "45-49": 47,
    "50-54": 52,
    "55-59": 57,
    "60-64": 62,
    "65-69": 67,
    "70-74": 72,
    "75-79": 77,
    "80+": 82,
    "80 or older": 82,
    "Age 18 to 24": 21,
    "Age 25 to 29": 27,
    "Age 30 to 34": 32,
    "Age 35 to 39": 37,
    "Age 40 to 44": 42,
    "Age 45 to 49": 47,
    "Age 50 to 54": 52,
    "Age 55 to 59": 57,
    "Age 60 to 64": 62,
    "Age 65 to 69": 67,
    "Age 70 to 74": 72,
    "Age 75 to 79": 77,
    "Age 80 or older": 82,
}

GENDER_MAP: dict[str, str] = {
    "Male": "male",
    "Female": "female",
    "male": "male",
    "female": "female",
}

# ETHNICITY_MAP: dict[str, str] = {
#     "White only, Non-Hispanic": "White",
#     "Black only, Non-Hispanic": "Black",
#     "Hispanic": "Hispanic",
#     "Asian only, Non-Hispanic": "Asian",
#     "Multiracial, Non-Hispanic": "Other",
#     "Other race only, Non-Hispanic": "Other",
#     "American Indian/Alaskan Native only, Non-Hispanic": "Native American",
#     "Native Hawaiian/other Pacific Islander only, Non-Hispanic": "Pacific Islander",
# }

CONDITION_MAP: dict[str, dict[str, str]] = {
    "HadHeartAttack": {"name": "Myocardial Infarction", "icd10": "I21"},
    "HadAngina": {"name": "Angina Pectoris", "icd10": "I20"},
    "HadStroke": {"name": "Stroke", "icd10": "I63"},
    "HadAsthma": {"name": "Asthma", "icd10": "J45"},
    "HadSkinCancer": {"name": "Skin Cancer", "icd10": "C44"},
    "HadCOPD": {"name": "COPD", "icd10": "J44"},
    "HadDepressiveDisorder": {"name": "Major Depressive Disorder", "icd10": "F32"},
    "HadKidneyDisease": {"name": "Chronic Kidney Disease", "icd10": "N18"},
    "HadArthritis": {"name": "Arthritis", "icd10": "M19"},
    "HadDiabetes": {"name": "Diabetes Mellitus", "icd10": "E11"},
}

US_STATES: list[str] = [
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
]


def _truthy(val: Any) -> bool:
    return val in ("Yes", "1", 1, True, "true")


def _parse_float(val: Any) -> float | None:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def transform_record(
    record: dict[str, str],
    index: int,
    enable_consent: bool,
) -> dict[str, Any]:
    patient_id = (record.get("PatientID") or "").strip() or f"kaggle_{index}"
    email = f"demo.patient{patient_id}@ulalo.com"

    age_cat = (record.get("AgeCategory") or "").strip()
    age = AGE_CATEGORY_MAP.get(age_cat, 35)

    sex = record.get("Sex") or ""
    gender = GENDER_MAP.get(sex, "other")

    race = (record.get("RaceEthnicityCategory") or "").strip()
    #   ethnicity = ETHNICITY_MAP.get(race, "Other")

    conditions: list[str] = []
    icd10_codes: list[str] = []
    for field, mapping in CONDITION_MAP.items():
        if _truthy(record.get(field)):
            conditions.append(mapping["name"])
            icd10_codes.append(mapping["icd10"])

    had_dm = record.get("HadDiabetes")
    if had_dm and str(had_dm) not in ("No", "0", "0.0", ""):
        if "Diabetes Mellitus" not in conditions:
            conditions.append("Diabetes Mellitus")
            icd10_codes.append("E11")

    height_m = _parse_float(record.get("HeightInMeters"))
    height = None
    if height_m is not None:
        height = {"number": round(height_m * 100), "unit": "cm"}

    weight_kg = _parse_float(record.get("WeightInKilograms"))
    weight = None
    if weight_kg is not None:
        weight = {"number": round(weight_kg * 10) / 10, "unit": "kg"}

    anthropometrics: dict[str, Any] | None = None
    if height or weight:
        anthropometrics = {}
        if height:
            anthropometrics["height"] = height
        if weight:
            anthropometrics["weight"] = weight

    state = (record.get("State") or "").strip() or random.choice(US_STATES)

    meta: dict[str, Any] = {
        "importedFrom": "kaggle",
        "kagglePatientId": patient_id,
        "generalHealth": record.get("GeneralHealth"),
        "bmi": _parse_float(record.get("BMI")),
        "smokerStatus": record.get("SmokerStatus"),
        "ecigaretteUsage": record.get("ECigaretteUsage"),
        "alcoholDrinkers": record.get("AlcoholDrinkers") == "Yes",
        "hivTesting": record.get("HIVTesting") == "Yes",
        "fluVaxLast12": record.get("FluVaxLast12") == "Yes",
        "pneumoVaxEver": record.get("PneumoVaxEver") == "Yes",
        "tetanusLast10Tdap": record.get("TetanusLast10Tdap"),
        "highRiskLastYear": record.get("HighRiskLastYear") == "Yes",
        "covidPos": record.get("CovidPos") == "Yes",
        "importedAt": datetime.now(timezone.utc).isoformat(),
    }

    out: dict[str, Any] = {
        "email": email,
        "name": f"Demo Patient {patient_id}",
        "display_patient_id": str(patient_id)[:64],
        "gender": gender,
        "age": age,
        "age_category": age_cat,
        "ethnicity": race,
        "anthropometrics": anthropometrics,
        "geography": {"country": "United States", "state": state},
        "patient_metadata": meta,
        "conditions": conditions,
        "icd10_codes": icd10_codes,
    }

    if enable_consent:
        out["clinical_trial_consent"] = {
            "enabled": True,
            "consentedAt": datetime.now(timezone.utc).isoformat(),
            "consentVersion": "demo-1.0",
        }
        out["trial_preferences"] = {
            "maxTravelDistance": 50 + random.randint(0, 99),
            "distanceUnit": "miles",
            "notificationFrequency": random.choice(["immediate", "daily", "weekly"]),
            "preferredPhases": ["II", "III"],
            "allowContactFromSponsors": random.random() > 0.5,
        }

    return out


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read and normalize CSV rows into memory.
    
    For 21K records this uses ~20-30MB which is acceptable.
    For larger files (100K+), consider streaming approach.
    """
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    (k or "").strip(): (v or "").strip() if v is not None else ""
                    for k, v in row.items()
                }
            )
    
    # Log patient ID range
    if rows:
        first_id = (rows[0].get("PatientID") or "unknown").strip()
        last_id = (rows[-1].get("PatientID") or "unknown").strip()
        logger.info(f"CSV loaded: {len(rows)} rows (Patient IDs: {first_id} to {last_id})")
    
    return rows


def stream_csv_rows(path: Path):
    """Generator that streams CSV rows one at a time (memory-efficient).

    Use this for very large files (100K+ rows) to avoid loading entire file into memory.
    """
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {
                (k or "").strip(): (v or "").strip() if v is not None else ""
                for k, v in row.items()
            }


def _should_process_row(row: dict[str, str], start_from: int) -> bool:
    """Check if row should be processed based on start_from filter.

    Args:
        row: CSV row dict
        start_from: Minimum patient ID number to process

    Returns:
        True if patient ID >= start_from, False otherwise
    """
    patient_id_str = (row.get("PatientID") or "").strip()

    # Handle kaggle_N format or pure numeric
    if patient_id_str.startswith("kaggle_"):
        patient_id_str = patient_id_str.replace("kaggle_", "")

    # Try to extract numeric ID
    try:
        patient_id_num = int(patient_id_str)
        return patient_id_num >= start_from
    except (ValueError, TypeError):
        # If can't parse, include by default (safety)
        logger.warning(f"Could not parse patient ID: {patient_id_str}, including in import")
        return True


async def insert_patient(
    session: AsyncSession, data: dict[str, Any], dry_run: bool, skip_patient_id_check: bool = False
) -> str:
    """Return 'inserted' | 'skipped_email' | 'dry_run'.

    Args:
        session: Database session
        data: Patient data dict
        dry_run: If True, don't actually insert
        skip_patient_id_check: If True, skip the display_patient_id duplicate check
                              (use when filtering via --start-from)
    """
    email = data["email"]

    # Check if email already exists
    existing_by_email = await session.scalar(select(User.id).where(User.email == email))
    if existing_by_email is not None:
        return "skipped_email"

    # Only check display_patient_id if not already filtered by start_from
    if not skip_patient_id_check:
        display_patient_id = data.get("display_patient_id")
        if display_patient_id:
            existing_by_patient_id = await session.scalar(
                select(Patient.id).where(Patient.display_patient_id == display_patient_id)
            )
            if existing_by_patient_id is not None:
                return "skipped_patient_id"

    if dry_run:
        return "dry_run"

    password_hash = _hash_demo_password()

    patient = Patient(
        email=email,
        password_hash=password_hash,
        name=data.get("name", "Demo Patient"),
        is_active=True,
        display_patient_id=data.get("display_patient_id"),
        gender=data.get("gender"),
        age=data.get("age"),
        age_category=data.get("age_category"),
        ethnicity=data.get("ethnicity"),
        anthropometrics=data.get("anthropometrics"),
        geography=data.get("geography"),
        conditions=data.get("conditions"),
        icd10_codes=data.get("icd10_codes"),
        patient_metadata=data.get("patient_metadata"),
        clinical_trial_consent=data.get("clinical_trial_consent"),
        trial_preferences=data.get("trial_preferences"),
    )
    session.add(patient)
    return "inserted"


async def run_import(
    file_path: Path,
    limit: int | None,
    batch_size: int,
    enable_consent: bool,
    dry_run: bool,
    workers: int = 1,
    streaming: bool = False,
    start_from: int | None = None,
    quiet_sql: bool = True,
) -> None:
    """Import patients with optional concurrent workers for large datasets.
    
    Args:
        file_path: Path to CSV file
        limit: Optional limit on number of rows to process
        batch_size: Commit every N rows per worker
        enable_consent: Whether to populate clinical trial consent fields
        dry_run: Parse and check duplicates only, no commits
        workers: Number of concurrent worker tasks (default: 1)
        streaming: Use queue-based streaming (memory-efficient for 100K+ rows)
        start_from: Only import patients with PatientID >= this value (e.g., 3900)
                   When set, skips display_patient_id database check for performance
        quiet_sql: Disable verbose SQL logging (default: True)
    """
    # Disable verbose SQL logging if requested
    if quiet_sql:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    # When using start_from, we can skip the display_patient_id database check
    # since we're filtering at the CSV level
    skip_patient_id_check = start_from is not None

    if streaming and workers > 1:
        # Queue-based streaming mode for very large files
        await _import_streaming(
            file_path,
            limit,
            batch_size,
            enable_consent,
            dry_run,
            workers,
            start_from,
            skip_patient_id_check,
        )
    else:
        # Load into memory (fine for 21K records, ~20-30MB)
        rows = read_csv_rows(file_path)

        # Filter by start_from if specified
        if start_from is not None:
            original_count = len(rows)
            first_before = (rows[0].get("PatientID") or "unknown").strip() if rows else "none"
            last_before = (rows[-1].get("PatientID") or "unknown").strip() if rows else "none"
            
            rows = [row for row in rows if _should_process_row(row, start_from)]
            
            first_after = (rows[0].get("PatientID") or "unknown").strip() if rows else "none"
            last_after = (rows[-1].get("PatientID") or "unknown").strip() if rows else "none"
            
            logger.info(
                "Applied start_from=%s filter:",
                start_from,
            )
            logger.info(f"  Before: {original_count} rows (IDs: {first_before} to {last_before})")
            logger.info(f"  After:  {len(rows)} rows (IDs: {first_after} to {last_after})")
            logger.info(f"  Filtered out: {original_count - len(rows)} rows")
            logger.info(f"  Optimization: Skipping display_patient_id DB checks")
            logger.info("")

        if limit is not None:
            rows = rows[:limit]

        total_rows = len(rows)
        logger.info("Rows to process: %s (dry_run=%s, workers=%s)", total_rows, dry_run, workers)

        if workers == 1:
            # Single-threaded mode (original behavior)
            await _import_worker(
                rows,
                batch_size,
                enable_consent,
                dry_run,
                worker_id=0,
                skip_patient_id_check=skip_patient_id_check,
            )
        else:
            # Multi-worker concurrent mode
            await _import_concurrent(
                rows, batch_size, enable_consent, dry_run, workers, skip_patient_id_check
            )


async def _import_worker(
    rows: list[dict[str, str]],
    batch_size: int,
    enable_consent: bool,
    dry_run: bool,
    worker_id: int,
    skip_patient_id_check: bool = False,
) -> dict[str, int]:
    """Single worker that processes a chunk of rows.

    Returns:
        Stats dict with inserted/skipped_email counts
    """
    inserted = skipped_email = skipped_patient_id = 0
    batch_count = 0

    async with AsyncSessionLocal() as session:
        for i, row in enumerate(rows):
            data = transform_record(row, i, enable_consent)
            status = await insert_patient(session, data, dry_run, skip_patient_id_check)
            if status == "inserted":
                inserted += 1
            elif status == "skipped_email":
                skipped_email += 1
            elif status == "skipped_patient_id":
                skipped_patient_id += 1

            batch_count += 1
            if batch_count >= batch_size:
                if not dry_run:
                    await session.commit()
                batch_count = 0
                if worker_id == 0 or len(rows) > 1000:
                    total_skipped = skipped_email + skipped_patient_id
                    logger.info(
                        "Worker %s progress: %s/%s (inserted=%s, skipped=%s)",
                        worker_id,
                        i + 1,
                        len(rows),
                        inserted,
                        total_skipped,
                    )

        if batch_count and not dry_run:
            await session.commit()

    return {
        "inserted": inserted,
        "skipped_email": skipped_email,
        "skipped_patient_id": skipped_patient_id,
    }


async def _import_concurrent(
    rows: list[dict[str, str]],
    batch_size: int,
    enable_consent: bool,
    dry_run: bool,
    workers: int,
    skip_patient_id_check: bool = False,
) -> None:
    """Distribute rows across multiple concurrent workers."""
    total_rows = len(rows)
    chunk_size = (total_rows + workers - 1) // workers  # Ceiling division

    logger.info(
        "Starting concurrent import: %s workers, ~%s rows per worker",
        workers,
        chunk_size,
    )

    start_time = time.time()

    # Create worker tasks
    tasks = []
    for worker_id in range(workers):
        start_idx = worker_id * chunk_size
        end_idx = min(start_idx + chunk_size, total_rows)
        chunk = rows[start_idx:end_idx]

        if chunk:
            logger.info(
                "Worker %s: processing rows %s-%s (%s rows)",
                worker_id,
                start_idx,
                end_idx - 1,
                len(chunk),
            )
            task = _import_worker(
                chunk, batch_size, enable_consent, dry_run, worker_id, skip_patient_id_check
            )
            tasks.append(task)

    # Run all workers concurrently
    results = await asyncio.gather(*tasks)

    # Aggregate statistics
    total_inserted = sum(r["inserted"] for r in results)
    total_skipped_email = sum(r["skipped_email"] for r in results)
    total_skipped_patient_id = sum(r["skipped_patient_id"] for r in results)
    total_skipped = total_skipped_email + total_skipped_patient_id
    elapsed = time.time() - start_time

    logger.info(
        "Import complete: inserted=%s, skipped=%s (email=%s, patient_id=%s), elapsed=%.2fs, throughput=%.0f rows/sec",
        total_inserted,
        total_skipped,
        total_skipped_email,
        total_skipped_patient_id,
        elapsed,
        total_rows / elapsed if elapsed > 0 else 0,
    )


async def _import_streaming(
    file_path: Path,
    limit: int | None,
    batch_size: int,
    enable_consent: bool,
    dry_run: bool,
    workers: int,
    start_from: int | None = None,
    skip_patient_id_check: bool = False,
) -> None:
    """Stream CSV rows via queue to workers (memory-efficient for very large files).

    Architecture:
    - Producer task reads CSV line-by-line and feeds into queue
    - Worker tasks consume from queue and process concurrently
    - No full file loaded into memory
    """
    queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue(maxsize=workers * 10)

    logger.info("Starting streaming import with queue (memory-efficient mode)")
    if start_from is not None:
        logger.info(f"Filtering: only importing patient IDs >= {start_from} (skipping DB check)")
    start_time = time.time()

    async def producer():
        """Read CSV and feed rows into queue (runs in executor to avoid blocking)."""
        count = 0
        filtered_count = 0
        
        # Run sync file reading in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        
        def sync_read():
            rows = []
            for row in stream_csv_rows(file_path):
                # Apply start_from filter
                if start_from is not None and not _should_process_row(row, start_from):
                    continue
                
                if limit is not None and len(rows) >= limit:
                    break
                rows.append(row)
            return rows
        
        # Read all filtered rows in executor
        rows = await loop.run_in_executor(None, sync_read)
        filtered_count = sum(1 for r in stream_csv_rows(file_path) if start_from and not _should_process_row(r, start_from)) if start_from else 0
        
        # Feed to queue (fast, async)
        for row in rows:
            await queue.put(row)
            count += 1

        # Send sentinel values to signal workers to stop
        for _ in range(workers):
            await queue.put(None)

        logger.info(f"Producer finished: {count} rows queued (filtered out: {filtered_count})")

    async def consumer(worker_id: int) -> dict[str, int]:
        """Worker that consumes from queue and processes rows."""
        inserted = skipped_email = skipped_patient_id = 0
        batch_count = 0
        row_count = 0

        async with AsyncSessionLocal() as session:
            while True:
                row = await queue.get()
                if row is None:
                    break

                data = transform_record(row, row_count, enable_consent)
                status = await insert_patient(session, data, dry_run, skip_patient_id_check)

                if status == "inserted":
                    inserted += 1
                elif status == "skipped_email":
                    skipped_email += 1
                elif status == "skipped_patient_id":
                    skipped_patient_id += 1

                row_count += 1
                batch_count += 1

                if batch_count >= batch_size:
                    if not dry_run:
                        await session.commit()
                    batch_count = 0
                    if worker_id == 0 and row_count % 1000 == 0:
                        total_skipped = skipped_email + skipped_patient_id
                        logger.info(
                            f"Worker {worker_id}: processed {row_count} rows "
                            f"(inserted={inserted}, skipped={total_skipped})"
                        )

                queue.task_done()

            if batch_count and not dry_run:
                await session.commit()

        return {
            "inserted": inserted,
            "skipped_email": skipped_email,
            "skipped_patient_id": skipped_patient_id,
        }

    # Start producer and consumers
    producer_task = asyncio.create_task(producer())
    consumer_tasks = [asyncio.create_task(consumer(i)) for i in range(workers)]

    # Wait for producer to finish
    await producer_task

    # Wait for all consumers to finish
    results = await asyncio.gather(*consumer_tasks)

    # Aggregate statistics
    total_inserted = sum(r["inserted"] for r in results)
    total_skipped_email = sum(r["skipped_email"] for r in results)
    total_skipped_patient_id = sum(r["skipped_patient_id"] for r in results)
    total_skipped = total_skipped_email + total_skipped_patient_id
    elapsed = time.time() - start_time
    total_rows = total_inserted + total_skipped

    logger.info(
        "Import complete: inserted=%s, skipped=%s (email=%s, patient_id=%s), elapsed=%.2fs, throughput=%.0f rows/sec",
        total_inserted,
        total_skipped,
        total_skipped_email,
        total_skipped_patient_id,
        elapsed,
        total_rows / elapsed if elapsed > 0 else 0,
    )


async def _async_main(args: argparse.Namespace) -> None:
    try:
        await run_import(
            Path(args.file).resolve(),
            limit=args.limit,
            batch_size=args.batch_size,
            enable_consent=args.enable_consent,
            dry_run=args.dry_run,
            workers=args.workers,
            streaming=args.streaming,
            start_from=args.start_from,
            quiet_sql=args.quiet_sql,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Kaggle-style patient CSV into PostgreSQL with concurrent workers."
    )
    parser.add_argument(
        "--file", required=True, help="Path to CSV (Kaggle CVD / BRFSS-style columns)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Max rows to import")
    parser.add_argument(
        "--batch-size", type=int, default=100, help="Commit every N rows per worker"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent workers (default: 1, recommended: 4-8 for 21K records)",
    )
    parser.add_argument(
        "--start-from",
        type=int,
        default=None,
        help="Only import patients with PatientID >= this value (e.g., --start-from 3900)",
    )
    parser.add_argument(
        "--streaming",
        action="store_true",
        help="Use queue-based streaming mode (memory-efficient for 100K+ rows)",
    )
    parser.add_argument(
        "--verbose-sql",
        action="store_true",
        default=False,
        help="Enable verbose SQL logging (default: disabled for cleaner output)",
    )
    parser.add_argument(
        "--disable-consent",
        action="store_true",
        default=False,
        help="Disable clinical_trial_consent and trial_preferences population",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and resolve skips only; no commits"
    )
    ns = parser.parse_args()
    
    # Set enable_consent based on --disable-consent flag
    ns.enable_consent = not ns.disable_consent
    # Set quiet_sql based on --verbose-sql flag
    ns.quiet_sql = not ns.verbose_sql
    
    asyncio.run(_async_main(ns))


if __name__ == "__main__":
    main()
