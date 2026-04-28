"""add age category

Revision ID: caef8ee42bf4
Revises: f3a9c2b8d1e4
Create Date: 2026-04-02 15:28:15.585402

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "caef8ee42bf4"
down_revision: Union[str, Sequence[str], None] = "f3a9c2b8d1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "patients",
        sa.Column("age_category", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("patients", "age_category")
