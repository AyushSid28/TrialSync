"""Patient profile; extends User via joined-table inheritance (same primary key)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models.user import User


class Patient(User):
    """Rows exist in both `users` (auth identity) and `patients` (clinical extensions)."""

    __tablename__ = "patients"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    display_patient_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Demographics (aligned with SmartPatient / Kaggle-style imports)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ethnicity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # e.g. {"height": {"number": 170, "unit": "cm"}, "weight": {"number": 70, "unit": "kg"}}
    anthropometrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    geography: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    conditions: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    icd10_codes: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    clinical_trial_consent: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    trial_preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    legacy_mongo_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    # DB column "metadata" — avoid Python attr name `metadata` (DeclarativeBase reserved).
    patient_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    # Full-text search vectors (auto-generated from JSONB columns via trigger)
    conditions_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
    )
    icd10_codes_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
    )
    # Full-text index for JSONB "metadata" (Kaggle import: bmi, smokerStatus, covidPos, etc.)
    metadata_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
    )

    __mapper_args__ = {
        "polymorphic_identity": "patient",
    }


async def search_patients_by_conditions(
    session: AsyncSession,
    query: str,
    *,
    mode: Literal["websearch", "plain", "phrase"] = "websearch",
    limit: int = 100,
    offset: int = 0,
) -> list[Patient]:
    """Search patients using ts_vector indexes on conditions, ICD-10 codes, and metadata JSON.

    Args:
        session: Active AsyncSession
        query: Search query (e.g., "diabetes cardiac", "hypertension", "E11 I20")
        mode: Query parsing mode:
            - "websearch": Natural web-style queries (default, handles AND/OR/NOT)
            - "plain": Plain text (all words as AND)
            - "phrase": Exact phrase matching
        limit: Maximum results to return
        offset: Pagination offset

    Returns:
        List of Patient objects ranked by relevance (highest first)

    Examples:
        # Natural language search
        patients = await search_patients_by_conditions(session, "diabetes cardiac")

        # ICD-10 code search
        patients = await search_patients_by_conditions(session, "E11 I20")

        # Exact phrase
        patients = await search_patients_by_conditions(
            session, "Major Depressive Disorder", mode="phrase"
        )
    """
    tsquery_func_map = {
        "websearch": "websearch_to_tsquery",
        "plain": "plainto_tsquery",
        "phrase": "phraseto_tsquery",
    }
    tsquery_func = tsquery_func_map.get(mode, "websearch_to_tsquery")

    # Combined tsvector: conditions, ICD-10 codes, and patient metadata (e.g. Kaggle JSON)
    tsquery_expr = text(f"{tsquery_func}('english', :query)")
    combined_tsv = (
        func.coalesce(Patient.conditions_tsv, text("''::tsvector"))
        + func.coalesce(Patient.icd10_codes_tsv, text("''::tsvector"))
        + func.coalesce(Patient.metadata_tsv, text("''::tsvector"))
    )

    stmt = (
        select(Patient)
        .where(combined_tsv.op("@@")(tsquery_expr))
        .order_by(func.ts_rank(combined_tsv, tsquery_expr).desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(stmt, {"query": query})
    return list(result.scalars().all())
