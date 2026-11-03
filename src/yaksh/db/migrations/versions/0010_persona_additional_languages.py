"""persona additional languages

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

LANGUAGE = postgresql.ENUM(name="language", create_type=False)


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column(
            "additional_languages",
            postgresql.ARRAY(LANGUAGE),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("personas", "additional_languages")
