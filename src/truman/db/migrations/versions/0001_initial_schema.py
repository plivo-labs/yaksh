"""initial schema: agents, personas, their versions, conversations

Revision ID: 0001
Revises:
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

agent_direction = postgresql.ENUM("inbound", "outbound", name="agent_direction", create_type=False)
agent_transport = postgresql.ENUM(
    "plivo_websocket", "phone", name="agent_transport", create_type=False
)
channel = postgresql.ENUM("voice", name="channel", create_type=False)
conversation_status = postgresql.ENUM(
    "queued",
    "running",
    "ending",
    "completed",
    "failed",
    "invalid",
    "cancelled",
    name="conversation_status",
    create_type=False,
)
end_reason = postgresql.ENUM(
    "user_request",
    "goal_reached",
    "agent_hangup",
    "duration_limit",
    "error",
    "process_restart",
    name="end_reason",
    create_type=False,
)
persona_language = postgresql.ENUM(
    "en", "hi", "hinglish", name="persona_language", create_type=False
)
voice_provider = postgresql.ENUM("elevenlabs", name="voice_provider", create_type=False)
ENUMS = (
    agent_direction,
    agent_transport,
    channel,
    conversation_status,
    end_reason,
    persona_language,
    voice_provider,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "agents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("direction", agent_direction, nullable=False),
        sa.Column("transport", agent_transport, nullable=False),
        sa.Column("websocket_url", sa.Text(), nullable=True),
        sa.Column("upgrade_headers", postgresql.JSONB(), nullable=False),
        sa.Column("extra_headers", postgresql.JSONB(), nullable=False),
        sa.Column("agent_number", sa.Text(), nullable=True),
        sa.Column("agent_speaks_first", sa.Boolean(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "transport <> 'plivo_websocket' OR websocket_url IS NOT NULL",
            name="ck_agents_websocket_url_required",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
    )
    op.create_index(
        "ix_agents_external_id_live",
        "agents",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "agent_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_agent_versions_agent_id_agents"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_versions"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_id_version"),
        sa.UniqueConstraint("id", "agent_id", name="uq_agent_versions_id_agent_id"),
    )

    op.create_table(
        "personas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("builtin_key", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("language", persona_language, nullable=False),
        sa.Column("voice_provider", voice_provider, nullable=False),
        sa.Column("voice_id", sa.Text(), nullable=False),
        sa.Column("voice_speed", sa.Float(), nullable=False),
        sa.Column("voice_stability", sa.Float(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_personas"),
        sa.UniqueConstraint("builtin_key", name="uq_personas_builtin_key"),
    )
    op.create_index(
        "ix_personas_name_live",
        "personas",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "persona_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], name="fk_persona_versions_persona_id_personas"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_persona_versions"),
        sa.UniqueConstraint("persona_id", "version", name="uq_persona_versions_persona_id_version"),
    )

    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", channel, nullable=False),
        sa.Column("persona_prompt", sa.Text(), nullable=False),
        sa.Column("caller_number", sa.Text(), nullable=False),
        sa.Column("max_duration_s", sa.Integer(), nullable=False),
        sa.Column("status", conversation_status, nullable=False),
        sa.Column("end_reason", end_reason, nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("recording_path", sa.Text(), nullable=True),
        sa.Column("transcript_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_conversations_agent_id_agents"
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "agent_id"],
            ["agent_versions.id", "agent_versions.agent_id"],
            name="fk_conversations_agent_version_id_agent_id_agent_versions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index(
        "ix_conversations_agent_created",
        "conversations",
        ["agent_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("conversations")
    op.drop_table("persona_versions")
    op.drop_table("personas")
    op.drop_table("agent_versions")
    op.drop_table("agents")
    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
