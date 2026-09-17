"""end reason no_answer

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-17
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

PREVIOUS = (
    "'user_request', 'goal_reached', 'goal_abandoned', 'agent_hangup', 'duration_limit', "
    "'error', 'process_restart'"
)


def upgrade() -> None:
    op.execute("ALTER TYPE end_reason ADD VALUE IF NOT EXISTS 'no_answer'")


def downgrade() -> None:
    op.execute("UPDATE conversations SET end_reason = 'error' WHERE end_reason = 'no_answer'")
    op.execute("ALTER TYPE end_reason RENAME TO end_reason_old")
    op.execute(f"CREATE TYPE end_reason AS ENUM ({PREVIOUS})")
    op.execute(
        "ALTER TABLE conversations ALTER COLUMN end_reason "
        "TYPE end_reason USING end_reason::text::end_reason"
    )
    op.execute("DROP TYPE end_reason_old")
