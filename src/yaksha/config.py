import inspect
from pathlib import Path
from typing import Annotated, Any

import asyncpg
from pydantic import Field, PostgresDsn, SecretStr, UrlConstraints, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url

from yaksha.db.session import SQLALCHEMY_ONLY
from yaksha.domain.numbers import E164

REPO_ROOT = Path(__file__).resolve().parents[2]
DatabaseUrl = Annotated[
    PostgresDsn,
    UrlConstraints(
        allowed_schemes=["postgres", "postgresql", "postgresql+asyncpg"], host_required=True
    ),
]
URL_OPTIONS = frozenset(inspect.signature(asyncpg.connect).parameters) | frozenset(SQLALCHEMY_ONLY)
"""The URL query options that SQLAlchemy and asyncpg take."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YAKSHA_",
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    api_host: str = "127.0.0.1"
    port: int | None = Field(default=None, validation_alias="PORT")
    api_token: SecretStr = Field(min_length=1)
    database_url: DatabaseUrl
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

    @field_validator("database_url")
    @classmethod
    def use_asyncpg(cls, url: PostgresDsn) -> PostgresDsn:
        """Hosts give postgres:// or postgresql:// URLs with libpq's sslmode, which asyncpg
        takes as ssl. An option asyncpg does not take is refused here, not at the first
        connection."""
        parsed = make_url(str(url))
        query = dict(parsed.query)
        if "sslmode" in query:
            if "ssl" in query:
                raise ValueError("give sslmode or ssl in the URL, not both")
            query["ssl"] = query.pop("sslmode")
        unknown = sorted(set(query) - URL_OPTIONS)
        if unknown:
            raise ValueError(
                f"remove from the URL what asyncpg does not take: {', '.join(unknown)}"
            )
        asyncpg_url = parsed.set(drivername="postgresql+asyncpg", query=query)
        return PostgresDsn(asyncpg_url.render_as_string(hide_password=False))

    # Required fields come from the environment; without this pyright demands them as arguments.
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
