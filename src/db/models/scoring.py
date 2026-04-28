"""Persistent models for DB-backed pipeline cache and scoring audit log."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class PipelineCacheEntry(Base):
    """Persistent, multi-worker pipeline cache for Text-to-SQL Stage 1 results.

    Replaces the in-process TTL dict — survives restarts and is shared across
    all worker processes without any in-memory state or locking.
    """

    __tablename__ = "pipeline_cache"

    __table_args__ = (
        Index("ix_pipeline_cache_expires_at", "expires_at"),
    )

    trial_id: Mapped[str] = mapped_column(Text, primary_key=True)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    patient_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ScoringAuditLog(Base):
    """Immutable audit record written after every scoring agent run.

    Captures the full pipeline context — criteria used, timing, generated SQL,
    eligibility parsing, and all scored patients — for reproducibility, diffing,
    and compliance.
    """

    __tablename__ = "scoring_audit_log"

    __table_args__ = (
        Index("ix_scoring_audit_log_trial_nct_id", "trial_nct_id"),
        Index("ix_scoring_audit_log_run_at", "run_at"),
        Index("ix_scoring_audit_log_trial_id", "trial_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    trial_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    trial_nct_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    trial_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    trial_status: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Actor tracking — populated from API key hash, user_id, or "system"
    triggered_by: Mapped[str | None] = mapped_column(String(256), nullable=True)

    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    criteria_used: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    pipeline_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    parsed_eligibility: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    icd10_codes_mapped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scoring_weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    scored_patients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
