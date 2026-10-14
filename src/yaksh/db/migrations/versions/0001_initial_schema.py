"""initial schema

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


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "manual", "file", "plivo_cx", "elevenlabs", "vapi", "retell", name="agent_source"
            ),
            nullable=False,
        ),
        sa.Column(
            "direction", sa.Enum("inbound", "outbound", name="agent_direction"), nullable=False
        ),
        sa.Column("transport", sa.Enum("phone", name="agent_transport"), nullable=False),
        sa.Column("agent_number", sa.Text(), nullable=True),
        sa.Column("outbound", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("agent_speaks_first", sa.Boolean(), nullable=False),
        sa.Column(
            "languages",
            postgresql.ARRAY(
                sa.Enum(
                    "en-US",
                    "en-IN",
                    "en-GB",
                    "en-AU",
                    "hi",
                    "bn",
                    "gu",
                    "kn",
                    "mr",
                    "ta",
                    "te",
                    "es",
                    name="agent_language",
                )
            ),
            nullable=False,
        ),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("config", sa.Text(), nullable=True),
        sa.Column(
            "knowledge_base",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forked_from_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["forked_from_id"], ["agents.id"], name=op.f("fk_agents_forked_from_id_agents")
        ),
        sa.CheckConstraint(
            "cardinality(languages) > 0", name=op.f("ck_agents_languages_not_empty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
    )
    op.create_index(
        "ix_agents_external_id_live",
        "agents",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "personas",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("builtin_key", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "language",
            sa.Enum("en", "hi", "bn", "gu", "kn", "mr", "ta", "te", "es", name="language"),
            nullable=False,
        ),
        sa.Column("voice_provider", sa.Enum("elevenlabs", name="voice_provider"), nullable=False),
        sa.Column("voice_id", sa.Text(), nullable=False),
        sa.Column("voice_speed", sa.Float(), nullable=False),
        sa.Column("voice_stability", sa.Float(), nullable=False),
        sa.Column(
            "voice_gender", sa.Enum("male", "female", "neutral", name="voice_gender"), nullable=True
        ),
        sa.Column("surroundings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sample_line", sa.Text(), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forked_from_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["forked_from_id"], ["personas.id"], name=op.f("fk_personas_forked_from_id_personas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personas")),
        sa.UniqueConstraint("builtin_key", name=op.f("uq_personas_builtin_key")),
    )
    op.create_index(
        "ix_personas_name_live",
        "personas",
        [sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "voices",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("provider", sa.Enum("elevenlabs", name="voice_provider"), nullable=False),
        sa.Column("provider_voice_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "gender", sa.Enum("male", "female", "neutral", name="voice_gender"), nullable=True
        ),
        sa.Column("accent", sa.Text(), nullable=True),
        sa.Column(
            "languages",
            postgresql.ARRAY(
                sa.Enum("en", "hi", "bn", "gu", "kn", "mr", "ta", "te", "es", name="language")
            ),
            nullable=False,
        ),
        sa.Column(
            "listed_languages",
            postgresql.ARRAY(
                sa.Enum("en", "hi", "bn", "gu", "kn", "mr", "ta", "te", "es", name="language")
            ),
            nullable=False,
        ),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "cardinality(languages) > 0", name=op.f("ck_voices_languages_not_empty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voices")),
    )
    op.create_index(
        "ix_voices_provider_voice_live",
        "voices",
        ["provider", "provider_voice_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_agent_versions_agent_id_agents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.UniqueConstraint("agent_id", "version", name=op.f("uq_agent_versions_agent_id_version")),
        sa.UniqueConstraint("id", "agent_id", name=op.f("uq_agent_versions_id_agent_id")),
    )
    op.create_table(
        "persona_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], name=op.f("fk_persona_versions_persona_id_personas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_persona_versions")),
        sa.UniqueConstraint("id", "persona_id", name=op.f("uq_persona_versions_id_persona_id")),
        sa.UniqueConstraint(
            "persona_id", "version", name=op.f("uq_persona_versions_persona_id_version")
        ),
    )
    op.create_table(
        "scenario_generations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column(
            "mode", sa.Enum("agent", "knowledge_base", name="generation_mode"), nullable=False
        ),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum("running", "done", "failed", "stopped", name="generation_status"),
            nullable=False,
        ),
        sa.Column("saved", sa.Integer(), nullable=False),
        sa.Column("dropped", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_scenario_generations_agent_id_agents")
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            name=op.f("fk_scenario_generations_agent_version_id_agent_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_generations")),
    )
    op.create_table(
        "scenarios",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "category",
            sa.Enum("happy_path", "messy_input", "edge_case", name="scenario_category"),
            server_default="happy_path",
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("generation_id", sa.UUID(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_scenarios_agent_id_agents")
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["scenario_generations.id"],
            name=op.f("fk_scenarios_generation_id_scenario_generations"),
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], name=op.f("fk_scenarios_persona_id_personas")
        ),
        sa.Column("forked_from_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["forked_from_id"],
            ["scenarios.id"],
            name=op.f("fk_scenarios_forked_from_id_scenarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenarios")),
        sa.UniqueConstraint("id", "agent_id", name=op.f("uq_scenarios_id_agent_id")),
    )
    op.create_index(
        "ix_scenarios_agent_name_live",
        "scenarios",
        ["agent_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "scenario_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_scenario_versions_scenario_id_scenarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_versions")),
        sa.UniqueConstraint("id", "scenario_id", name=op.f("uq_scenario_versions_id_scenario_id")),
        sa.UniqueConstraint(
            "scenario_id", "version", name=op.f("uq_scenario_versions_scenario_id_version")
        ),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("repeats", sa.Integer(), nullable=False),
        sa.Column("max_duration_s", sa.Integer(), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("max_parallel", sa.Integer(), nullable=True),
        sa.Column("start_interval_s", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=True),
        sa.Column("request_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(request_key IS NULL) = (request_hash IS NULL)",
            name=op.f("ck_runs_request_together"),
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name=op.f("fk_runs_agent_id_agents")),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "agent_id"],
            ["agent_versions.id", "agent_versions.agent_id"],
            name=op.f("fk_runs_agent_version_id_agent_id_agent_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
        sa.UniqueConstraint("id", "agent_id", name=op.f("uq_runs_id_agent_id")),
        sa.UniqueConstraint("request_key", name=op.f("uq_runs_request_key")),
    )
    op.create_index(
        "ix_runs_agent_created",
        "runs",
        ["agent_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.Enum("voice", name="channel"), nullable=False),
        sa.Column(
            "direction", sa.Enum("inbound", "outbound", name="agent_direction"), nullable=False
        ),
        sa.Column("persona_id", sa.UUID(), nullable=False),
        sa.Column("persona_version_id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column("scenario_version_id", sa.UUID(), nullable=False),
        sa.Column("data_set_id", sa.UUID(), nullable=False),
        sa.Column("data_set_name", sa.Text(), nullable=False),
        sa.Column(
            "language",
            sa.Enum("en", "hi", "bn", "gu", "kn", "mr", "ta", "te", "es", name="language"),
            nullable=False,
        ),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("nudge", sa.Text(), nullable=False),
        sa.Column("today", sa.Date(), nullable=False),
        sa.Column("time_zone", sa.Text(), nullable=False),
        sa.Column("caller_number", sa.Text(), nullable=True),
        sa.Column("call_uuid", sa.Text(), nullable=True),
        sa.Column("dial_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_caller_id", sa.Text(), nullable=True),
        sa.Column("max_duration_s", sa.Integer(), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("surroundings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sound_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "ending",
                "completed",
                "failed",
                "invalid",
                "cancelled",
                name="conversation_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "end_reason",
            sa.Enum(
                "user_request",
                "caller_hangup",
                "agent_hangup",
                "agent_silent",
                "no_answer",
                "stream_ended",
                "duration_limit",
                "error",
                "worker_stopped",
                "lease_lost",
                "trigger_failed",
                "no_call",
                "turn_limit",
                name="end_reason",
            ),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("talk_ms", sa.Integer(), nullable=True),
        sa.Column("recording_key", sa.Text(), nullable=True),
        sa.Column("caller_voice_key", sa.Text(), nullable=True),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("caller_reason", sa.Text(), nullable=True),
        sa.Column("caller_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("caller_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("line_facts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("repeat", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("retry_of", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt >= 1 AND (retry_of IS NULL) = (attempt = 1)",
            name=op.f("ck_conversations_retry_is_later_attempt"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_conversations_agent_id_agents")
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "agent_id"],
            ["agent_versions.id", "agent_versions.agent_id"],
            name=op.f("fk_conversations_agent_version_id_agent_id_agent_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], name=op.f("fk_conversations_persona_id_personas")
        ),
        sa.ForeignKeyConstraint(
            ["persona_version_id", "persona_id"],
            ["persona_versions.id", "persona_versions.persona_id"],
            name=op.f("fk_conversations_persona_version_id_persona_id_persona_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id", "agent_id"],
            ["scenarios.id", "scenarios.agent_id"],
            name=op.f("fk_conversations_scenario_id_agent_id_scenarios"),
        ),
        sa.ForeignKeyConstraint(
            ["scenario_version_id", "scenario_id"],
            ["scenario_versions.id", "scenario_versions.scenario_id"],
            name=op.f("fk_conversations_scenario_version_id_scenario_id_scenario_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "agent_id"],
            ["runs.id", "runs.agent_id"],
            name=op.f("fk_conversations_run_id_agent_id_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["retry_of"], ["conversations.id"], name=op.f("fk_conversations_retry_of_conversations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint(
            "run_id",
            "repeat",
            "scenario_id",
            "persona_id",
            "data_set_id",
            "attempt",
            name=op.f("uq_conversations_run_id_repeat_scenario_id_persona_id_data_set_id_attempt"),
        ),
    )
    op.create_index(
        "ix_conversations_agent_created",
        "conversations",
        ["agent_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_conversations_status_created", "conversations", ["status", "created_at"], unique=False
    )
    op.create_index(
        "ix_conversations_run_status", "conversations", ["run_id", "status"], unique=False
    )
    op.create_index("ix_conversations_retry_of", "conversations", ["retry_of"], unique=False)
    op.create_table(
        "evaluations",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "state",
            sa.Enum("queued", "running", "done", "failed", name="evaluation_state"),
            nullable=False,
        ),
        sa.Column("code_version", sa.Text(), nullable=True),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("claim_seq", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scenario_verdict", sa.Enum("pass", "fail", "not_scored", name="verdict"), nullable=True
        ),
        sa.Column(
            "conversation_verdict",
            sa.Enum("pass", "fail", "not_scored", name="verdict"),
            nullable=True,
        ),
        sa.Column(
            "effective_scenario_verdict",
            sa.Enum("pass", "fail", "not_scored", name="verdict"),
            nullable=True,
        ),
        sa.Column(
            "effective_conversation_verdict",
            sa.Enum("pass", "fail", "not_scored", name="verdict"),
            nullable=True,
        ),
        sa.Column("jev_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("audit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name=op.f("uq_evaluations_conversation_id")),
    )
    op.create_index(
        "ix_evaluations_state_created", "evaluations", ["state", "created_at"], unique=False
    )
    op.create_table(
        "metric_values",
        sa.Column("evaluation_id", sa.UUID(), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "flags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"]),
        sa.PrimaryKeyConstraint("evaluation_id", "metric_key"),
    )
    op.create_table(
        "judge_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("judge", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_sha256", sa.Text(), nullable=False),
        sa.Column("schema_sha256", sa.Text(), nullable=False),
        sa.Column("evidence_view_version", sa.Integer(), nullable=False),
        sa.Column("code_checks_version", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_sha256", name=op.f("uq_judge_versions_content_sha256")),
    )
    op.create_table(
        "evaluation_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("evaluation_id", sa.UUID(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("judge_version_id", sa.UUID(), nullable=True),
        sa.Column("decided_by", sa.Enum("code", "jev", "llm", name="decided_by"), nullable=False),
        sa.Column("role", sa.Enum("deciding", "reporting", name="item_role"), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "evidence_checks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "machine_outcome",
            sa.Enum(
                "pass",
                "fail",
                "not_applicable",
                "unsure",
                "blocked",
                "error",
                "pending",
                name="outcome",
            ),
            nullable=False,
        ),
        sa.Column(
            "unsure_kind",
            sa.Enum("hidden_action", "not_confirmed_played", "unclear", name="unsure_kind"),
            nullable=True,
        ),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column("caller_effect", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("jev_version_id", sa.UUID(), nullable=True),
        sa.Column("jev_choice", sa.Text(), nullable=True),
        sa.Column("jev_probabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "effective_outcome",
            sa.Enum(
                "pass",
                "fail",
                "not_applicable",
                "unsure",
                "blocked",
                "error",
                "pending",
                name="outcome",
            ),
            nullable=False,
        ),
        sa.Column(
            "effective_unsure_kind",
            sa.Enum("hidden_action", "not_confirmed_played", "unclear", name="unsure_kind"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"]),
        sa.ForeignKeyConstraint(["jev_version_id"], ["judge_versions.id"]),
        sa.ForeignKeyConstraint(["judge_version_id"], ["judge_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id", "item_key", name=op.f("uq_evaluation_items_evaluation_id_item_key")
        ),
    )
    op.create_table(
        "labelers",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labelers")),
        sa.UniqueConstraint("name", name=op.f("uq_labelers_name")),
        sa.UniqueConstraint("token_sha256", name=op.f("uq_labelers_token_sha256")),
    )
    op.create_table(
        "labels",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("labeler_id", sa.UUID(), nullable=False),
        sa.Column("lane", sa.Enum("audit", "ad_hoc", name="lane"), nullable=False),
        sa.Column("blind", sa.Boolean(), nullable=False),
        sa.Column(
            "answer",
            sa.Enum(
                "pass", "fail", "not_applicable", "cannot_tell", "blocked", name="label_answer"
            ),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Enum(
                "agent_error",
                "applicability",
                "transcript_error",
                "spoken_form",
                "date_or_time",
                "read_back",
                "window_or_order",
                "exact_value",
                "hidden_action",
                "evidence_misread",
                "criterion_ambiguous",
                "caller_error",
                "scenario_error",
                "test_settings_error",
                "line_or_audio",
                "other",
                name="label_reason",
            ),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason <> 'other' OR btrim(coalesce(note, '')) <> ''",
            name=op.f("ck_labels_other_has_note"),
        ),
        sa.CheckConstraint(
            "answer IN ('pass', 'not_applicable') OR reason IS NOT NULL",
            name=op.f("ck_labels_problem_has_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["evaluation_items.id"], name=op.f("fk_labels_item_id_evaluation_items")
        ),
        sa.ForeignKeyConstraint(
            ["labeler_id"], ["labelers.id"], name=op.f("fk_labels_labeler_id_labelers")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labels")),
    )
    op.create_index("ix_labels_item_id", "labels", ["item_id"], unique=False)
    op.create_table(
        "judge_calls",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("request_sha256", sa.Text(), nullable=False),
        sa.Column("model_returned", sa.Text(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["evaluation_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "refused_calls",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("call_uuid", sa.Text(), nullable=False),
        sa.Column("to_number", sa.Text(), nullable=False),
        sa.Column("from_number", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_uuid"),
    )
    op.create_index(
        "ix_conversations_run_started", "conversations", ["run_id", "started_at"], unique=False
    )
    op.create_table(
        "phone_numbers",
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("voice", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("application_id", sa.Text(), nullable=True),
        sa.Column("application_name", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_after", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_phone_numbers_conversation_id_conversations"),
        ),
        sa.PrimaryKeyConstraint("number", name=op.f("pk_phone_numbers")),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("empty_pages", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(storage_key IS NULL) = (media_type IS NULL)"
            " AND (storage_key IS NULL) = (size_bytes IS NULL)"
            " AND (storage_key IS NULL) = (sha256 IS NULL)",
            name=op.f("ck_documents_file_fields_together"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_table(
        "workers",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("receiving_app_id", sa.Text(), nullable=True),
        sa.Column("outbound_problem", sa.Text(), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workers")),
    )
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "secrets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_app_settings_one_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_settings")),
    )
    op.execute("INSERT INTO app_settings (id) VALUES (1)")
    op.create_table(
        "phone_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_phone_checks_one_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_checks")),
    )
    op.execute("INSERT INTO phone_checks (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("phone_checks")
    op.drop_table("app_settings")
    op.drop_table("workers")
    op.drop_table("documents")
    op.drop_table("phone_numbers")
    op.drop_table("labels")
    op.drop_table("labelers")
    op.drop_table("judge_calls")
    op.drop_table("evaluation_items")
    op.drop_table("judge_versions")
    op.drop_table("metric_values")
    op.drop_table("evaluations")
    op.drop_table("refused_calls")
    op.drop_table("conversations")
    op.drop_table("runs")
    op.drop_table("scenario_versions")
    op.drop_table("scenarios")
    op.drop_table("scenario_generations")
    op.drop_table("persona_versions")
    op.drop_table("agent_versions")
    op.drop_table("voices")
    op.drop_table("personas")
    op.drop_table("agents")
    for enum in (
        "end_reason",
        "conversation_status",
        "channel",
        "voice_gender",
        "voice_provider",
        "language",
        "agent_language",
        "agent_transport",
        "agent_direction",
        "agent_source",
        "scenario_category",
        "generation_mode",
        "generation_status",
        "evaluation_state",
        "verdict",
        "outcome",
        "unsure_kind",
        "decided_by",
        "item_role",
        "lane",
        "label_answer",
        "label_reason",
    ):
        op.execute(f"DROP TYPE {enum}")
