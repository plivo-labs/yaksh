import inspect
from pathlib import Path
from typing import Annotated, Any, Self

import asyncpg
from pydantic import (
    Field,
    PostgresDsn,
    SecretStr,
    UrlConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from yaksh.db.session import SQLALCHEMY_ONLY

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
        env_prefix="YAKSH_",
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
    allow_private_hosts: bool = False
    """Allow trigger and text agent URLs on private or local addresses, for development."""
    public_url: str | None = None
    s3_endpoint: str | None = None
    """Where files are kept, uploaded documents and call audio: any S3-compatible service.
    Unset: AWS S3."""
    s3_bucket: str = "yaksh"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    """Both or neither. Neither: the AWS credential chain, such as an IAM role."""
    s3_region: str = "us-east-1"
    encryption_key: SecretStr = Field(min_length=32)
    """Encrypts the secrets stored with the settings. Without the key they are lost."""

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

    @model_validator(mode="after")
    def s3_keys_together(self) -> Self:
        if (self.s3_access_key is None) != (self.s3_secret_key is None):
            raise ValueError("give the S3 access key and secret key together, or neither")
        return self

    # Required fields come from the environment; without this pyright demands them as arguments.
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
