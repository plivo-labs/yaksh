"""phone checks and voice numbers

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("phone_numbers", "enabled")
    op.add_column(
        "phone_numbers",
        sa.Column("voice", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_table(
        "phone_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_phone_checks_one_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_checks")),
    )
    op.execute("INSERT INTO phone_checks (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("phone_checks")
    op.drop_column("phone_numbers", "voice")
    op.add_column(
        "phone_numbers",
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
