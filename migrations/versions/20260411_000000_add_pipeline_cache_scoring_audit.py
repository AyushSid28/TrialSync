"""Add pipeline_cache and scoring_audit_log tables for persistent cache and audit trail.

Revision ID: e5f9a2b3c4d1
Revises: d4e8f1a92c0b
Create Date: 2026-04-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5f9a2b3c4d1"
down_revision = "d4e8f1a92c0b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- pipeline_cache ---
    op.create_table(
        "pipeline_cache",
        sa.Column("trial_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column(
            "patient_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pipeline_cache_expires_at",
        "pipeline_cache",
        ["expires_at"],
    )

    # --- scoring_audit_log ---
    op.create_table(
        "scoring_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("trial_id", sa.Text(), nullable=True),
        sa.Column("trial_nct_id", sa.Text(), nullable=True),
        sa.Column("trial_title", sa.Text(), nullable=True),
        sa.Column("trial_status", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(256), nullable=True),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "criteria_used",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "pipeline_info",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "parsed_eligibility",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("icd10_codes_mapped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "scoring_weights",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "scored_patients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ix_scoring_audit_log_trial_nct_id",
        "scoring_audit_log",
        ["trial_nct_id"],
    )
    op.create_index(
        "ix_scoring_audit_log_run_at",
        "scoring_audit_log",
        ["run_at"],
    )
    op.create_index(
        "ix_scoring_audit_log_trial_id",
        "scoring_audit_log",
        ["trial_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scoring_audit_log_trial_id", table_name="scoring_audit_log")
    op.drop_index("ix_scoring_audit_log_run_at", table_name="scoring_audit_log")
    op.drop_index("ix_scoring_audit_log_trial_nct_id", table_name="scoring_audit_log")
    op.drop_table("scoring_audit_log")

    op.drop_index("ix_pipeline_cache_expires_at", table_name="pipeline_cache")
    op.drop_table("pipeline_cache")
