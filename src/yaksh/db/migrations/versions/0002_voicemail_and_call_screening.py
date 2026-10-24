"""voicemail and call screening

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OLD_KEY = "uq_conversations_run_id_repeat_scenario_id_persona_id_data_set_id_attempt"
ANSWERED_BY = postgresql.ENUM("caller", "voicemail", "screener", name="answered_by")


def upgrade() -> None:
    ANSWERED_BY.create(op.get_bind())
    op.add_column(
        "conversations",
        sa.Column("answered_by", ANSWERED_BY, server_default="caller", nullable=False),
    )
    op.drop_constraint(op.f(OLD_KEY), "conversations", type_="unique")
    op.create_unique_constraint(
        "uq_conversations_attempt",
        "conversations",
        ["run_id", "repeat", "scenario_id", "persona_id", "data_set_id", "answered_by", "attempt"],
    )
    op.add_column(
        "personas",
        sa.Column(
            "answering",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute("ALTER TYPE end_reason ADD VALUE 'voicemail_ended'")
    op.execute("ALTER TYPE end_reason ADD VALUE 'screener_ended'")


def downgrade() -> None:
    """Postgres cannot drop an enum value, so end_reason keeps the two new ones."""
    op.drop_column("personas", "answering")
    op.drop_constraint("uq_conversations_attempt", "conversations", type_="unique")
    op.create_unique_constraint(
        op.f(OLD_KEY),
        "conversations",
        ["run_id", "repeat", "scenario_id", "persona_id", "data_set_id", "attempt"],
    )
    op.drop_column("conversations", "answered_by")
    ANSWERED_BY.drop(op.get_bind())
