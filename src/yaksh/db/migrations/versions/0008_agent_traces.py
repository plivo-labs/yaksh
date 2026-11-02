"""agent traces

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents", sa.Column("traces_linked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "agent_spans",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("span_id", sa.Text(), nullable=False),
        sa.Column("parent_span_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("start_ns", sa.BigInteger(), nullable=False),
        sa.Column("end_ns", sa.BigInteger(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("link_conversation_id", sa.UUID(), nullable=True),
        sa.Column("link_number", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_spans")),
        sa.UniqueConstraint("trace_id", "span_id", name=op.f("uq_agent_spans_trace_id_span_id")),
    )
    op.create_index(
        "ix_agent_spans_link_conversation_id",
        "agent_spans",
        ["link_conversation_id"],
        postgresql_where=sa.text("link_conversation_id IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_spans_link_number_start_ns",
        "agent_spans",
        ["link_number", "start_ns"],
        postgresql_where=sa.text("link_number IS NOT NULL"),
    )
    op.create_index("ix_agent_spans_received_at", "agent_spans", ["received_at"])
    op.create_table(
        "agent_trace_owners",
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_agent_trace_owners_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("trace_id", name=op.f("pk_agent_trace_owners")),
    )
    op.create_index(
        op.f("ix_agent_trace_owners_conversation_id"), "agent_trace_owners", ["conversation_id"]
    )
    op.create_table(
        "trace_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_sha256", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_key_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_trace_tokens_one_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trace_tokens")),
    )


def downgrade() -> None:
    op.drop_table("trace_tokens")
    op.drop_index(op.f("ix_agent_trace_owners_conversation_id"), table_name="agent_trace_owners")
    op.drop_table("agent_trace_owners")
    op.drop_index("ix_agent_spans_received_at", table_name="agent_spans")
    op.drop_index("ix_agent_spans_link_number_start_ns", table_name="agent_spans")
    op.drop_index("ix_agent_spans_link_conversation_id", table_name="agent_spans")
    op.drop_table("agent_spans")
    op.drop_column("agents", "traces_linked_at")
