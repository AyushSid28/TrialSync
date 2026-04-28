"""Clinical trials ingested from US (NCT) and EU (EudraCT) scrapers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class ClinicalTrial(Base):
    """Unified row; full nested scrape document lives in `payload` (JSONB)."""

    __tablename__ = "clinical_trials"

    __table_args__ = (
        CheckConstraint(
            "(nct_id IS NOT NULL AND eudract_number IS NULL) OR "
            "(nct_id IS NULL AND eudract_number IS NOT NULL)",
            name="ck_clinical_trials_single_registry_id",
        ),
        Index(
            "uq_clinical_trials_nct_id",
            "nct_id",
            unique=True,
            postgresql_where=text("nct_id IS NOT NULL"),
        ),
        Index(
            "uq_clinical_trials_eudract_number",
            "eudract_number",
            unique=True,
            postgresql_where=text("eudract_number IS NOT NULL"),
        ),
        Index("ix_clinical_trials_registry", "registry"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    registry: Mapped[str] = mapped_column(String(8), nullable=False)
    nct_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    eudract_number: Mapped[str | None] = mapped_column(Text, nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    sponsor: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[str | None] = mapped_column(Text, nullable=True)

    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
