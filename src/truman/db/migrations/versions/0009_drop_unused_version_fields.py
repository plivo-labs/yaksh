"""drop the unused version label and change kind

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
    op.execute("ALTER TYPE agent_change RENAME TO agent_change_old")
    op.execute("CREATE TYPE agent_change AS ENUM ('created', 'changed')")
    op.execute(
        "ALTER TABLE agent_versions ALTER COLUMN change "
        "TYPE agent_change USING change::text::agent_change"
    )
    op.execute("DROP TYPE agent_change_old")


def downgrade() -> None:
    op.execute("ALTER TYPE agent_change ADD VALUE IF NOT EXISTS 'restored'")
    op.add_column("agent_versions", sa.Column("label", sa.Text(), nullable=True))
