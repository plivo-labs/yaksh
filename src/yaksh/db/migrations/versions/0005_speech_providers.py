"""voices of other text-to-speech providers

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NEW_PROVIDERS = ("cartesia", "sarvam", "azure", "nimble")


def upgrade() -> None:
    for provider in NEW_PROVIDERS:
        op.execute(f"ALTER TYPE voice_provider ADD VALUE IF NOT EXISTS '{provider}'")
    op.alter_column("personas", "voice_stability", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    """Postgres cannot drop an enum value, so the new providers stay in voice_provider."""
    op.execute("UPDATE personas SET voice_stability = 0.5 WHERE voice_stability IS NULL")
    op.alter_column("personas", "voice_stability", existing_type=sa.Float(), nullable=False)
