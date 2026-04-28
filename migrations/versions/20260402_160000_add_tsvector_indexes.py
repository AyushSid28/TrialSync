"""Add tsvector indexes for conditions and icd10_codes full-text search.

Revision ID: 20260402_160000
Revises: 20260402_152815_add_age_category
Create Date: 2026-04-02 16:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "caef8ee42ef4"
down_revision = "caef8ee42bf4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add tsvector columns for full-text search (no defaults - will populate via trigger)
    op.add_column(
        "patients",
        sa.Column(
            "conditions_tsv",
            postgresql.TSVECTOR(),
            nullable=True,
        ),
    )
    op.add_column(
        "patients",
        sa.Column(
            "icd10_codes_tsv",
            postgresql.TSVECTOR(),
            nullable=True,
        ),
    )

    # Create GIN indexes for fast full-text search
    op.create_index(
        "ix_patients_conditions_tsv",
        "patients",
        ["conditions_tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_patients_icd10_codes_tsv",
        "patients",
        ["icd10_codes_tsv"],
        postgresql_using="gin",
    )

    # Create triggers to auto-update tsvector columns when JSONB columns change
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION patients_tsvector_trigger()
            RETURNS trigger AS $$
            BEGIN
                NEW.conditions_tsv := to_tsvector('english', coalesce(NEW.conditions::text, ''));
                NEW.icd10_codes_tsv := to_tsvector('english', coalesce(NEW.icd10_codes::text, ''));
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TRIGGER patients_tsvector_update
            BEFORE INSERT OR UPDATE OF conditions, icd10_codes ON patients
            FOR EACH ROW
            EXECUTE FUNCTION patients_tsvector_trigger();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS patients_tsvector_update ON patients"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS patients_tsvector_trigger()"))
    op.drop_index("ix_patients_icd10_codes_tsv", table_name="patients")
    op.drop_index("ix_patients_conditions_tsv", table_name="patients")
    op.drop_column("patients", "icd10_codes_tsv")
    op.drop_column("patients", "conditions_tsv")
