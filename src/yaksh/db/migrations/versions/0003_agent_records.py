"""agent records

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

RECORD_STATE = postgresql.ENUM("found", "missing", name="record_state", create_type=False)
RECORD_PROVIDER = postgresql.ENUM("plivo_cx", name="record_provider", create_type=False)


def upgrade() -> None:
    RECORD_STATE.create(op.get_bind())
    RECORD_PROVIDER.create(op.get_bind())
    op.add_column(
        "agents", sa.Column("record_source", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("conversations", sa.Column("trigger_response", sa.Text(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("clock_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "agent_records",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("state", RECORD_STATE, nullable=False),
        sa.Column("provider", RECORD_PROVIDER, nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("record", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("conversation_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_records")
    op.drop_column("conversations", "clock_started_at")
    op.drop_column("conversations", "trigger_response")
    op.drop_column("agents", "record_source")
    RECORD_PROVIDER.drop(op.get_bind())
    RECORD_STATE.drop(op.get_bind())
