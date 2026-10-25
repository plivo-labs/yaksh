"""test suites

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TRANSPORT = postgresql.ENUM("phone", "text", name="agent_transport", create_type=False)
ANSWERED_BY = postgresql.ENUM(
    "caller", "voicemail", "screener", name="answered_by", create_type=False
)
"""Both types belong to earlier revisions; this one never creates or drops them."""


def upgrade() -> None:
    op.create_table(
        "suites",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("required_pass_percent", sa.SmallInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
            "required_pass_percent BETWEEN 1 AND 100",
            name=op.f("ck_suites_required_pass_percent_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suites")),
    )
    op.create_index(
        "ix_suites_name_live",
        "suites",
        [sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "suite_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("transport", TRANSPORT, nullable=False),
        sa.Column("all_scenarios_answered_by", postgresql.ARRAY(ANSWERED_BY), nullable=True),
        sa.Column("repeats", sa.Integer(), nullable=False),
        sa.Column("max_duration_s", sa.Integer(), nullable=True),
        sa.Column("max_turns", sa.Integer(), nullable=True),
        sa.Column("max_parallel", sa.Integer(), nullable=True),
        sa.Column("start_interval_s", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.CheckConstraint("position >= 1", name=op.f("ck_suite_entries_position_from_1")),
        sa.CheckConstraint(
            "all_scenarios_answered_by IS NULL OR cardinality(all_scenarios_answered_by) > 0",
            name=op.f("ck_suite_entries_all_scenarios_answers_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["suites.id"],
            name=op.f("fk_suite_entries_suite_id_suites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_suite_entries_agent_id_agents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suite_entries")),
        sa.UniqueConstraint(
            "suite_id", "position", name=op.f("uq_suite_entries_suite_id_position")
        ),
        sa.UniqueConstraint("id", "agent_id", name=op.f("uq_suite_entries_id_agent_id")),
    )
    op.create_table(
        "suite_entry_scenarios",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("data_set_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column("answered_by", postgresql.ARRAY(ANSWERED_BY), nullable=False),
        sa.CheckConstraint("position >= 1", name=op.f("ck_suite_entry_scenarios_position_from_1")),
        sa.CheckConstraint(
            "cardinality(answered_by) > 0 AND "
            "(data_set_ids IS NULL OR cardinality(data_set_ids) > 0)",
            name=op.f("ck_suite_entry_scenarios_lists_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "agent_id"],
            ["suite_entries.id", "suite_entries.agent_id"],
            name=op.f("fk_suite_entry_scenarios_entry_id_agent_id_suite_entries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id", "agent_id"],
            ["scenarios.id", "scenarios.agent_id"],
            name=op.f("fk_suite_entry_scenarios_scenario_id_agent_id_scenarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suite_entry_scenarios")),
        sa.UniqueConstraint(
            "entry_id", "position", name=op.f("uq_suite_entry_scenarios_entry_id_position")
        ),
        sa.UniqueConstraint(
            "entry_id", "scenario_id", name=op.f("uq_suite_entry_scenarios_entry_id_scenario_id")
        ),
    )
    op.create_table(
        "suite_entry_scenario_personas",
        sa.Column("entry_scenario_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "position >= 1", name=op.f("ck_suite_entry_scenario_personas_position_from_1")
        ),
        sa.ForeignKeyConstraint(
            ["entry_scenario_id"],
            ["suite_entry_scenarios.id"],
            name="fk_suite_entry_scenario_personas_entry_scenario",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["personas.id"],
            name=op.f("fk_suite_entry_scenario_personas_persona_id_personas"),
        ),
        sa.PrimaryKeyConstraint(
            "entry_scenario_id", "position", name=op.f("pk_suite_entry_scenario_personas")
        ),
        sa.UniqueConstraint(
            "entry_scenario_id",
            "persona_id",
            name=op.f("uq_suite_entry_scenario_personas_entry_scenario_id_persona_id"),
        ),
    )
    op.create_table(
        "suite_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("required_pass_percent", sa.SmallInteger(), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "required_pass_percent BETWEEN 1 AND 100",
            name=op.f("ck_suite_runs_required_pass_percent_range"),
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"], ["suites.id"], name=op.f("fk_suite_runs_suite_id_suites")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suite_runs")),
        sa.UniqueConstraint("request_key", name=op.f("uq_suite_runs_request_key")),
    )
    op.create_index(
        "ix_suite_runs_suite_created",
        "suite_runs",
        ["suite_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.add_column("runs", sa.Column("suite_run_id", sa.UUID(), nullable=True))
    op.add_column("runs", sa.Column("suite_position", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_runs_suite_run_id_suite_runs"), "runs", "suite_runs", ["suite_run_id"], ["id"]
    )
    op.create_unique_constraint(
        "uq_runs_suite_position", "runs", ["suite_run_id", "suite_position"]
    )
    op.create_check_constraint(
        op.f("ck_runs_suite_position_together"),
        "runs",
        "(suite_run_id IS NULL) = (suite_position IS NULL)",
    )
    op.create_check_constraint(op.f("ck_runs_suite_position_from_1"), "runs", "suite_position >= 1")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_runs_suite_position_from_1"), "runs", type_="check")
    op.drop_constraint(op.f("ck_runs_suite_position_together"), "runs", type_="check")
    op.drop_constraint("uq_runs_suite_position", "runs", type_="unique")
    op.drop_constraint(op.f("fk_runs_suite_run_id_suite_runs"), "runs", type_="foreignkey")
    op.drop_column("runs", "suite_position")
    op.drop_column("runs", "suite_run_id")
    op.drop_index("ix_suite_runs_suite_created", table_name="suite_runs")
    op.drop_table("suite_runs")
    op.drop_table("suite_entry_scenario_personas")
    op.drop_table("suite_entry_scenarios")
    op.drop_table("suite_entries")
    op.drop_index("ix_suites_name_live", table_name="suites")
    op.drop_table("suites")
