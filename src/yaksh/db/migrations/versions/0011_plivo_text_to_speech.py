"""nimble voices become plivo voices

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

MODEL = "koyal-v1"
MODEL_COLUMNS = (
    "UPDATE voices SET model = :model WHERE provider::text = :provider",
    "UPDATE personas SET voice_model = :model WHERE voice_provider::text = :provider",
    "UPDATE persona_versions SET voice_model = :model"
    " WHERE config -> 'voice' ->> 'provider' = :provider",
)
VOICE_COPIES = (("persona_versions", "config"), ("conversations", "caller_settings"))
"""The JSON columns that hold a copy of a voice, with its provider."""


def upgrade() -> None:
    """The voices get the model `koyal-v1` and the provider gets Plivo's name. Nimble's address,
    Auth ID and Auth token are deleted: that address answers 404, and a key goes only to the
    address it was checked at, so Plivo's Auth ID and Auth token are saved again."""
    set_model("nimble", MODEL)
    rename("nimble", "plivo")
    op.execute(
        "UPDATE app_settings SET values = values - 'nimble',"
        " secrets = secrets - 'nimble_auth_id' - 'nimble_auth_token'"
    )


def downgrade() -> None:
    """The deleted address, Auth ID and Auth token do not come back: save them again."""
    set_model("plivo", None)
    rename("plivo", "nimble")


def set_model(provider: str, model: str | None) -> None:
    for statement in MODEL_COLUMNS:
        op.get_bind().execute(sa.text(statement), {"model": model, "provider": provider})


def rename(old: str, new: str) -> None:
    op.execute(f"ALTER TYPE voice_provider RENAME VALUE '{old}' TO '{new}'")
    for table, column in VOICE_COPIES:
        op.execute(
            f"UPDATE {table} SET {column} = jsonb_set({column}, '{{voice,provider}}', '\"{new}\"')"
            f" WHERE {column} -> 'voice' ->> 'provider' = '{old}'"
        )
