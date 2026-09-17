"""agents are reached by phone only

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

STALE = """
SELECT (SELECT count(*) FROM agents WHERE transport = 'plivo_websocket')
     + (SELECT count(*) FROM agent_versions WHERE config->>'transport' = 'plivo_websocket')
"""


def upgrade() -> None:
    stale = op.get_bind().execute(sa.text(STALE)).scalar_one()
    if stale:
        raise RuntimeError(
            f"{stale} agents or agent versions still use the plivo_websocket transport; "
            "delete those agents and their conversations before upgrading"
        )
    op.execute(
        "UPDATE agent_versions SET config = config - 'websocket_url' - 'upgrade_headers' "
        "- 'extra_headers'"
    )
    for name in (
        "ck_agents_websocket_url_required",
        "ck_agents_ck_agents_websocket_url_required",
        "ck_agents_agent_number_required",
    ):
        op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {name}")
    op.drop_column("agents", "websocket_url")
    op.drop_column("agents", "upgrade_headers")
    op.drop_column("agents", "extra_headers")
    op.alter_column("agents", "agent_number", nullable=False)
    op.execute("ALTER TYPE agent_transport RENAME TO agent_transport_old")
    op.execute("CREATE TYPE agent_transport AS ENUM ('phone')")
    op.execute(
        "ALTER TABLE agents ALTER COLUMN transport "
        "TYPE agent_transport USING transport::text::agent_transport"
    )
    op.execute("DROP TYPE agent_transport_old")


def downgrade() -> None:
    op.execute("ALTER TYPE agent_transport RENAME TO agent_transport_old")
    op.execute("CREATE TYPE agent_transport AS ENUM ('plivo_websocket', 'phone')")
    op.execute(
        "ALTER TABLE agents ALTER COLUMN transport "
        "TYPE agent_transport USING transport::text::agent_transport"
    )
    op.execute("DROP TYPE agent_transport_old")
    op.alter_column("agents", "agent_number", nullable=True)
    op.add_column("agents", sa.Column("websocket_url", sa.Text(), nullable=True))
    op.add_column(
        "agents",
        sa.Column("upgrade_headers", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "agents",
        sa.Column("extra_headers", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT ck_agents_websocket_url_required "
        "CHECK (transport <> 'plivo_websocket' OR websocket_url IS NOT NULL)"
    )
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT ck_agents_agent_number_required "
        "CHECK (transport <> 'phone' OR agent_number IS NOT NULL)"
    )
