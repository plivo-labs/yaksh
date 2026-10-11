from pydantic import BaseModel, Field, SecretStr

from yaksha.domain.settings import AppSettings, SecretName, SettingsValues, Url
from yaksha.settings.service import Provider


class SecretState(BaseModel):
    """A saved secret, never its value."""

    hint: str | None
    """The last 4 characters, so the page can show which key is saved; None for a value under
    12 characters, where 4 would give away too much of it."""


class SettingsRead(BaseModel):
    version: int
    """Grows with every change."""
    values: SettingsValues
    secrets: dict[SecretName, SecretState]
    """Each saved secret; a secret that is not saved is left out."""
    trigger_secrets: dict[str, SecretState]
    """Each saved trigger secret, by the name a template uses as {{secrets.NAME}}."""

    @classmethod
    def of(cls, settings: AppSettings) -> SettingsRead:
        secrets = settings.secrets
        return cls(
            version=settings.version,
            values=SettingsValues.model_validate(
                settings.model_dump(exclude={"version", "secrets"})
            ),
            secrets={
                name: SecretState(hint=hint(value))
                for name in SecretName
                if (value := getattr(secrets, name.value)) is not None
            },
            trigger_secrets={
                name: SecretState(hint=hint(value))
                for name, value in sorted(secrets.triggers.items())
            },
        )


def hint(value: SecretStr) -> str | None:
    plain = value.get_secret_value()
    return plain[-4:] if len(plain) >= 12 else None


class SecretWrite(BaseModel):
    value: str = Field(min_length=1, max_length=4000)
    url: Url | None = None
    """The new address of a key that has one, saved with the key; the key is checked there.
    None keeps the saved address."""


class PlivoAccount(BaseModel):
    auth_id: str = Field(min_length=1, max_length=200)
    auth_token: str = Field(min_length=1, max_length=4000)


class SigningKey(BaseModel):
    key: str
    """Shown this one time; copy it to the agent's system."""


class ProviderTest(BaseModel):
    provider: Provider
    ok: bool
    detail: str
    """What worked, or why the test failed."""


class Models(BaseModel):
    models: list[str]
    """The model ids the LLM provider lists."""


class Efforts(BaseModel):
    model: str
    efforts: list[str]
    """The reasoning efforts the model takes; empty for a model without reasoning."""


class SettingsImport(BaseModel):
    document: str = Field(max_length=200_000)
    """A YAML settings document, as the export writes it."""
    env: dict[str, str] = {}
    """Values for the ${NAME} placeholders of secrets; the CLI sends the ones it found in its
    environment. A placeholder without a value is skipped."""
    dry_run: bool = False
    """List the changes without saving them or checking any key."""


class ImportResult(BaseModel):
    changes: list[str]
    """One line for each change, without secret values."""
    skipped: list[str]
    """Secrets whose ${NAME} had no value; they stay as they are."""
    failed: list[str]
    """Keys that failed their check, with the reason; they were not saved."""
    settings: SettingsRead
    """The settings after the import; as they are now on a dry run."""
