"""Add tsvector index for patients.metadata (patient_metadata) full-text search.

Revision ID: d4e8f1a92c0b
Revises: caef8ee42ef4
Create Date: 2026-04-03 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4e8f1a92c0b"
down_revision = "caef8ee42ef4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "metadata_tsv",
            postgresql.TSVECTOR(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_patients_metadata_tsv",
        "patients",
        ["metadata_tsv"],
        postgresql_using="gin",
    )

    op.execute(sa.text("DROP TRIGGER IF EXISTS patients_tsvector_update ON patients"))

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION patients_tsvector_trigger()
            RETURNS trigger AS $$
            BEGIN
                NEW.conditions_tsv := to_tsvector('english', coalesce(NEW.conditions::text, ''));
                NEW.icd10_codes_tsv := to_tsvector('english', coalesce(NEW.icd10_codes::text, ''));
                NEW.metadata_tsv := to_tsvector('english', coalesce(NEW.metadata::text, ''));
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
            BEFORE INSERT OR UPDATE OF conditions, icd10_codes, metadata ON patients
            FOR EACH ROW
            EXECUTE FUNCTION patients_tsvector_trigger();
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE patients
            SET metadata_tsv = to_tsvector('english', coalesce(metadata::text, ''));
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS patients_tsvector_update ON patients"))

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

    op.drop_index("ix_patients_metadata_tsv", table_name="patients")
    op.drop_column("patients", "metadata_tsv")
