"""a text-to-speech model for each voice

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

INDEX = "ix_voices_provider_voice_live"
MODELS = {
    "elevenlabs": ("elevenlabs", ("eleven_flash_v2_5", "eleven_multilingual_v2")),
    "cartesia": ("cartesia", ("sonic-3.6", "sonic-3.5", "sonic-3")),
    "sarvam": ("sarvam_tts", ("bulbul:v4-flash", "bulbul:v3")),
}
"""Each provider with a model choice: the Settings section that held its one model, and the
models that the previous release could speak with. A stored model outside the list becomes the
first, the default the Settings page showed. ElevenLabs' v3 and v4 are left out: its socket of
the previous release refused them, so no voice ever spoke with them."""


def upgrade() -> None:
    connection = op.get_bind()
    values = connection.execute(sa.text("SELECT values FROM app_settings")).scalar() or {}
    op.add_column("voices", sa.Column("model", sa.Text(), nullable=True))
    op.add_column("personas", sa.Column("voice_model", sa.Text(), nullable=True))
    op.add_column("persona_versions", sa.Column("voice_model", sa.Text(), nullable=True))
    for provider, (section, models) in MODELS.items():
        stored = (values.get(section) or {}).get("model")
        model = stored if stored in models else models[0]
        for statement in (
            "UPDATE voices SET model = :model WHERE provider::text = :provider",
            "UPDATE personas SET voice_model = :model WHERE voice_provider::text = :provider",
            "UPDATE persona_versions SET voice_model = :model"
            " WHERE config -> 'voice' ->> 'provider' = :provider",
        ):
            connection.execute(sa.text(statement), {"model": model, "provider": provider})
    connection.execute(
        sa.text(
            "UPDATE app_settings SET version = version + 1,"
            " values = values #- '{elevenlabs,model}' #- '{cartesia,model}' #- '{sarvam_tts,model}'"
        )
    )
    op.drop_index(INDEX, table_name="voices")
    op.create_index(
        INDEX,
        "voices",
        ["provider", "provider_voice_id", "model"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Fails while two live voices share a provider and an ID; restore the backup instead."""
    op.drop_index(INDEX, table_name="voices")
    op.create_index(
        INDEX,
        "voices",
        ["provider", "provider_voice_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_column("persona_versions", "voice_model")
    op.drop_column("personas", "voice_model")
    op.drop_column("voices", "model")
