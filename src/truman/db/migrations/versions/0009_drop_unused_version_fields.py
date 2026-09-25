"""drop the unused version label

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("agent_versions", "label")


def downgrade() -> None:
    op.add_column("agent_versions", sa.Column("label", sa.Text(), nullable=True))
