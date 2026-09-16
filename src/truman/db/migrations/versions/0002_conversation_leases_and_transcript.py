"""conversation leases and transcript column

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("claimed_by", sa.Text(), nullable=True))
    op.add_column(
        "conversations", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("conversations", sa.Column("transcript", postgresql.JSONB(), nullable=True))
    op.drop_column("conversations", "transcript_path")
    op.create_index("ix_conversations_status_created", "conversations", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_conversations_status_created", table_name="conversations")
    op.add_column("conversations", sa.Column("transcript_path", sa.Text(), nullable=True))
    op.drop_column("conversations", "transcript")
    op.drop_column("conversations", "lease_expires_at")
    op.drop_column("conversations", "claimed_by")
