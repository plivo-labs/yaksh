from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from yaksha.domain.numbers import E164

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YAKSHA_",
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        validate_by_name=True,
    )

    api_host: str = "127.0.0.1"
    port: int | None = Field(default=None, validation_alias="PORT")
    api_token: SecretStr = Field(min_length=1)
    database_url: PostgresDsn
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"
    max_active_conversations: int = 4
    worker_poll_interval_s: float = 0.5
    worker_heartbeat_s: float = 1.0
    worker_lease_s: int = 30
    evaluator_poll_interval_s: float = 2.0
    evaluator_lease_s: int = 60
    evaluator_concurrency: int = 2
    evaluator_judge_concurrency: int = Field(default=8, gt=0)
    """Judge model calls in flight across one evaluator's evaluations."""
    end_timeout_s: float = 5.0
    plivo_numbers: Annotated[list[E164], NoDecode] = []
    plivo_app_id: str | None = None
    """The Plivo Application that sends outbound test calls to this worker."""
    allow_private_triggers: bool = False
    """Allow trigger URLs on private or local addresses, for development."""
    public_url: str | None = None
    s3_endpoint: str
    """Where files are kept, uploaded documents and call audio: any S3-compatible service."""
    s3_bucket: str = "yaksha"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_region: str = "us-east-1"
    encryption_key: SecretStr = Field(min_length=32)
    """Encrypts the secrets stored with the settings. Without the key they are lost."""

    @field_validator("plivo_numbers", mode="before")
    @classmethod
    def split_numbers(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [number.strip() for number in value.split(",") if number.strip()]
        return value

    # Required fields come from the environment; without this pyright demands them as arguments.
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
