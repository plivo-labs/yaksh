from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from truman.domain.agents import E164

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRUMAN_", env_file=".env", extra="ignore", validate_by_name=True
    )

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_token: SecretStr = Field(min_length=1)
    database_url: PostgresDsn
    data_dir: Path = REPO_ROOT / "data"
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"
    default_max_duration_s: int = 300
    max_active_conversations: int = 4
    worker_poll_interval_s: float = 0.5
    worker_heartbeat_s: float = 1.0
    worker_lease_s: int = 30
    end_timeout_s: float = 5.0
    deepgram_api_key: SecretStr | None = Field(default=None, validation_alias="DEEPGRAM_API_KEY")
    deepgram_url: str = ""
    deepgram_model: str = "nova-3"
    elevenlabs_api_key: SecretStr | None = Field(
        default=None, validation_alias="ELEVENLABS_API_KEY"
    )
    azure_openai_endpoint: str | None = Field(
        default=None, validation_alias="AZURE_OPENAI_ENDPOINT"
    )
    azure_openai_api_key: SecretStr | None = Field(
        default=None, validation_alias="AZURE_OPENAI_API_KEY"
    )
    azure_openai_api_version: str | None = Field(
        default=None, validation_alias="AZURE_OPENAI_API_VERSION"
    )
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    persona_model: str = "gpt-4.1"
    plivo_auth_id: SecretStr | None = Field(default=None, validation_alias="PLIVO_AUTH_ID")
    plivo_auth_token: SecretStr | None = Field(default=None, validation_alias="PLIVO_AUTH_TOKEN")
    plivo_numbers: Annotated[list[E164], NoDecode] = []
    public_url: str | None = None
    stream_port: int = 8770
    ring_timeout_s: int = 30
    timezone: str = "UTC"
    """The zone of the date the caller is told is today."""

    @property
    def phone_enabled(self) -> bool:
        return (
            self.plivo_auth_id is not None
            and self.plivo_auth_token is not None
            and self.public_url is not None
        )

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown time zone: {value}") from error
        return value

    @field_validator("plivo_numbers", mode="before")
    @classmethod
    def split_numbers(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [number.strip() for number in value.split(",") if number.strip()]
        return value

    # Required fields come from the environment; without this pyright demands them as arguments.
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
