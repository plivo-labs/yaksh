"""voices of other text-to-speech providers

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
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
