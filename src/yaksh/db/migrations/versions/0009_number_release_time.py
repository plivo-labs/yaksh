"""number release time

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "phone_numbers", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("phone_numbers", "released_at")
