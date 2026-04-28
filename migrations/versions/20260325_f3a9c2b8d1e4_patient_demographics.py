"""Add patient demographics columns for Kaggle-style imports.

Revision ID: f3a9c2b8d1e4
Revises: e17536fcb1b7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f3a9c2b8d1e4"
down_revision = "e17536fcb1b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("gender", sa.String(length=32), nullable=True))
    op.add_column("patients", sa.Column("age", sa.Integer(), nullable=True))
    op.add_column("patients", sa.Column("ethnicity", sa.String(length=64), nullable=True))
    op.add_column(
        "patients",
        sa.Column("anthropometrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("patients", "anthropometrics")
    op.drop_column("patients", "ethnicity")
    op.drop_column("patients", "age")
    op.drop_column("patients", "gender")
