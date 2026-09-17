"""phone numbers from the account

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("phone_numbers", sa.Column("alias", sa.Text(), nullable=True))
    op.add_column("phone_numbers", sa.Column("region", sa.Text(), nullable=True))
    op.add_column(
        "phone_numbers",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("phone_numbers", "enabled")
    op.drop_column("phone_numbers", "region")
    op.drop_column("phone_numbers", "alias")
