"""caller reply times

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("caller_reply_times", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_conversations_started", "conversations", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_conversations_started", table_name="conversations")
    op.drop_column("conversations", "caller_reply_times")
