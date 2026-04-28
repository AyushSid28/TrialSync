"""
Scrape recruiting US studies from ClinicalTrials.gov API v2 into PostgreSQL (ClinicalTrial ORM).

Requires DATABASE_URL in the environment (.env). Run from project root:

    uv run python -m src.scrappers.us_clinical_trials_scrapping
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from urllib3.util.retry import Retry

from src.core.config import settings
from src.db.models.clinical_trial import ClinicalTrial
from src.db.session import AsyncSessionLocal, engine

# Import settings loads .env — validates required fields at import time
_ = settings

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_retry_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    return session


def extract_locations(trial_data: dict[str, Any]) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    protocol_section = trial_data.get("protocolSection", {})
    sites_module = protocol_section.get("contactsLocationsModule", {})
    locations_list = sites_module.get("locations", [])

    for loc in locations_list:
        location_info = {
            "facility": loc.get("facility", ""),
            "city": loc.get("city", ""),
            "state": loc.get("state", ""),
            "zip": loc.get("zip", ""),
            "country": loc.get("country", ""),
        }
        location_parts = [
            p
            for p in (location_info["city"], location_info["state"], location_info["country"])
            if p
        ]
        location_str = ", ".join(location_parts) if location_parts else None
        if location_str:
            location_info["full_location"] = location_str
            locations.append(location_info)

    if not locations:
        contacts = sites_module.get("centralContacts", [])
        for contact in contacts:
            if contact.get("city") or contact.get("country"):
                loc = {
                    "city": contact.get("city", ""),
                    "country": contact.get("country", ""),
                    "full_location": f"{contact.get('city', '')}, {contact.get('country', '')}".strip(
                        ", "
                    ),
                }
                if loc["full_location"]:
                    locations.append(loc)

    return locations


def extract_eligibility_details(eligibility_module: dict[str, Any] | None) -> dict[str, Any]:
    if not eligibility_module:
        return {}

    return {
        "eligibilityCriteria": eligibility_module.get("eligibilityCriteria", ""),
        "healthyVolunteers": eligibility_module.get("healthyVolunteers", False),
        "sex": eligibility_module.get("sex", "ALL"),
        "minimumAge": eligibility_module.get("minimumAge", ""),
        "maximumAge": eligibility_module.get("maximumAge", ""),
        "stdAges": eligibility_module.get("stdAges", []),
        "studyPopulation": eligibility_module.get("studyPopulation", ""),
        "samplingMethod": eligibility_module.get("samplingMethod", ""),
    }


def process_trial(trial_data: dict[str, Any]) -> dict[str, Any] | None:
    protocol_section = trial_data.get("protocolSection", {})
    identification = protocol_section.get("identificationModule", {})
    status_module = protocol_section.get("statusModule", {})
    conditions_module = protocol_section.get("conditionsModule", {})
    sponsor_module = protocol_section.get("sponsorCollaboratorsModule", {})
    eligibility_module = protocol_section.get("eligibilityModule", {})
    design_module = protocol_section.get("designModule", {})
    description_module = protocol_section.get("descriptionModule", {})

    nct_id = identification.get("nctId")
    if not nct_id:
        return None

    locations = extract_locations(trial_data)
    eligibility = extract_eligibility_details(eligibility_module)

    return {
        "nct_id": nct_id,
        "title": identification.get("briefTitle", ""),
        "official_title": identification.get("officialTitle", ""),
        "acronym": identification.get("acronym", ""),
        "status": status_module.get("overallStatus", ""),
        "start_date": status_module.get("startDateStruct", {}).get("date", ""),
        "completion_date": status_module.get("completionDateStruct", {}).get("date", ""),
        "last_update_date": status_module.get("lastUpdatePostDateStruct", {}).get("date", ""),
        "conditions": conditions_module.get("conditions", []),
        "keywords": conditions_module.get("keywords", []),
        "sponsor": sponsor_module.get("leadSponsor", {}).get("name", ""),
        "collaborators": [c.get("name", "") for c in sponsor_module.get("collaborators", [])],
        "eligibility": eligibility,
        "phase": design_module.get("phases", []),
        "study_type": design_module.get("studyType", ""),
        "allocation": design_module.get("allocation", ""),
        "intervention_model": design_module.get("interventionModel", ""),
        "primary_purpose": design_module.get("primaryPurpose", ""),
        "brief_summary": description_module.get("briefSummary", ""),
        "detailed_description": description_module.get("detailedDescription", ""),
        "locations": locations,
        "location_countries": list(
            {loc.get("country", "") for loc in locations if loc.get("country")}
        ),
        "location_cities": list({loc.get("city", "") for loc in locations if loc.get("city")}),
        "source": "ClinicalTrials.gov",
        "region": "US",
        "scraped_at": datetime.now(timezone.utc),
    }


def doc_to_jsonable(obj: Any) -> Any:
    """Make structures safe for JSONB (datetime -> ISO string)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: doc_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [doc_to_jsonable(v) for v in obj]
    return obj


async def upsert_clinical_trial(session: AsyncSession, doc: dict[str, Any]) -> None:
    """Insert or update a US trial row keyed by nct_id."""
    nct_id = doc["nct_id"]
    scraped_at = doc["scraped_at"]
    if not isinstance(scraped_at, datetime):
        scraped_at = datetime.now(timezone.utc)

    payload = doc_to_jsonable(doc)

    existing = await session.scalar(select(ClinicalTrial).where(ClinicalTrial.nct_id == nct_id))

    def _text(val: Any) -> str | None:
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

    if existing:
        existing.registry = "US"
        existing.eudract_number = None
        existing.title = _text(doc.get("title")) or existing.title
        existing.sponsor = _text(doc.get("sponsor")) or existing.sponsor
        existing.status = _text(doc.get("status")) or existing.status
        existing.start_date = _text(doc.get("start_date")) or existing.start_date
        existing.source = _text(doc.get("source")) or existing.source
        existing.source_url = _text(doc.get("source_url")) or existing.source_url
        existing.scraped_at = scraped_at
        existing.payload = payload
    else:
        session.add(
            ClinicalTrial(
                registry="US",
                nct_id=nct_id,
                eudract_number=None,
                title=_text(doc.get("title")),
                sponsor=_text(doc.get("sponsor")),
                status=_text(doc.get("status")),
                start_date=_text(doc.get("start_date")),
                source=_text(doc.get("source")),
                source_url=_text(doc.get("source_url")),
                scraped_at=scraped_at,
                payload=payload,
            )
        )


async def save_trials_pg(trials: list[dict[str, Any]]) -> int:
    """Process API study dicts and upsert into clinical_trials. Returns rows processed."""
    docs: list[dict[str, Any]] = []
    for trial in trials:
        doc = process_trial(trial)
        if doc:
            docs.append(doc)

    if not docs:
        return 0

    async with AsyncSessionLocal() as session:
        for doc in docs:
            await upsert_clinical_trial(session, doc)
        await session.commit()

    return len(docs)


def fetch_trials(page_token: str | None = None) -> dict[str, Any]:
    session = get_retry_session()
    params: dict[str, Any] = {"query.term": "Recruiting", "pageSize": 100}
    if page_token:
        params["pageToken"] = page_token

    resp = session.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def run(max_trials: int | None = 500) -> int:
    logger.info("=" * 80)
    logger.info("US clinical trials scraper -> PostgreSQL (clinical_trials)")
    logger.info("=" * 80)
    logger.info("Limit: %s", max_trials if max_trials else "none")
    logger.info("=" * 80 + "\n")

    page_token: str | None = None
    total = 0
    page_num = 1

    while True:
        logger.info("Page %s — fetching...", page_num)
        try:
            data = fetch_trials(page_token)
        except Exception as e:
            logger.error("Fetch failed: %s", e)
            break

        trials = data.get("studies", [])
        if not trials:
            logger.info("No studies returned; stopping.")
            break

        if max_trials is not None:
            remaining = max_trials - total
            if remaining <= 0:
                break
            if len(trials) > remaining:
                trials = trials[:remaining]

        logger.info("Received %s studies", len(trials))
        time.sleep(0.5)

        try:
            n = await save_trials_pg(trials)
            logger.info("Upserted %s rows", n)
        except Exception as e:
            logger.exception("Database upsert failed: %s", e)
            break

        total += len(trials)

        if max_trials is not None and total >= max_trials:
            logger.info("Reached max_trials=%s", max_trials)
            break

        page_token = data.get("nextPageToken")
        if not page_token:
            logger.info("No further pages.")
            break

        page_num += 1
        time.sleep(0.5)

    logger.info("=" * 80)
    logger.info("Done: processed %s API studies total", total)
    logger.info("=" * 80)

    async with AsyncSessionLocal() as session:
        cnt = await session.scalar(
            select(func.count()).select_from(ClinicalTrial).where(ClinicalTrial.registry == "US")
        )
        logger.info("US trials in DB (registry=US): %s", cnt)

    return total


async def _async_main(max_trials: int | None) -> None:
    try:
        await run(max_trials=max_trials)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape US recruiting trials into PostgreSQL.")
    parser.add_argument(
        "--max-trials",
        type=int,
        default=200,
        help="Stop after this many API studies (omit or use 0 for no limit)",
    )
    args = parser.parse_args()
    limit: int | None = args.max_trials if args.max_trials and args.max_trials > 0 else None
    asyncio.run(_async_main(limit))


if __name__ == "__main__":
    main()
