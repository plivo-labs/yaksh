"""phone numbers pool, call uuid, nullable caller number, agent number rule, constraint name fix

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agents RENAME CONSTRAINT ck_agents_ck_agents_websocket_url_required "
        "TO ck_agents_websocket_url_required"
    )
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT ck_agents_agent_number_required "
        "CHECK (transport <> 'phone' OR agent_number IS NOT NULL)"
    )
    op.add_column("conversations", sa.Column("call_uuid", sa.Text(), nullable=True))
    op.alter_column("conversations", "caller_number", nullable=True)
    op.create_table(
        "phone_numbers",
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_phone_numbers_conversation_id_conversations",
        ),
        sa.PrimaryKeyConstraint("number", name="pk_phone_numbers"),
    )


def downgrade() -> None:
    op.drop_table("phone_numbers")
    op.execute(
        "UPDATE conversations SET caller_number = '+15550100000' WHERE caller_number IS NULL"
    )
    op.alter_column("conversations", "caller_number", nullable=False)
    op.drop_column("conversations", "call_uuid")
    op.execute("ALTER TABLE agents DROP CONSTRAINT ck_agents_agent_number_required")
    op.execute(
        "ALTER TABLE agents RENAME CONSTRAINT ck_agents_websocket_url_required "
        "TO ck_agents_ck_agents_websocket_url_required"
    )
