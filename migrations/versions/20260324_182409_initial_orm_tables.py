"""Initial users, patients, clinical_trials tables.

Revision ID: 20250324_001
Revises:
Create Date: 2025-03-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e17536fcb1b7"

down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_type", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_user_type"), "users", ["user_type"], unique=False)

    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_patient_id", sa.String(length=64), nullable=True),
        sa.Column("geography", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("icd10_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("clinical_trial_consent", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trial_preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("legacy_mongo_id", sa.String(length=24), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_patients_display_patient_id"), "patients", ["display_patient_id"], unique=False
    )
    op.create_index(
        op.f("ix_patients_legacy_mongo_id"), "patients", ["legacy_mongo_id"], unique=False
    )

    op.create_table(
        "clinical_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry", sa.String(length=8), nullable=False),
        sa.Column("nct_id", sa.Text(), nullable=True),
        sa.Column("eudract_number", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("sponsor", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Text(), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(nct_id IS NOT NULL AND eudract_number IS NULL) OR "
            "(nct_id IS NULL AND eudract_number IS NOT NULL)",
            name="ck_clinical_trials_single_registry_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clinical_trials_registry", "clinical_trials", ["registry"], unique=False)
    op.create_index(
        "uq_clinical_trials_nct_id",
        "clinical_trials",
        ["nct_id"],
        unique=True,
        postgresql_where=sa.text("nct_id IS NOT NULL"),
    )
    op.create_index(
        "uq_clinical_trials_eudract_number",
        "clinical_trials",
        ["eudract_number"],
        unique=True,
        postgresql_where=sa.text("eudract_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_clinical_trials_eudract_number", table_name="clinical_trials")
    op.drop_index("uq_clinical_trials_nct_id", table_name="clinical_trials")
    op.drop_index("ix_clinical_trials_registry", table_name="clinical_trials")
    op.drop_table("clinical_trials")

    op.drop_index(op.f("ix_patients_legacy_mongo_id"), table_name="patients")
    op.drop_index(op.f("ix_patients_display_patient_id"), table_name="patients")
    op.drop_table("patients")

    op.drop_index(op.f("ix_users_user_type"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
