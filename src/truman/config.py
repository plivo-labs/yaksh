from pathlib import Path
from typing import Any, Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    default_caller_number: str = "+15550100000"
    default_max_duration_s: int = 300
    max_active_conversations: int = 4
    worker_poll_interval_s: float = 0.5
    worker_heartbeat_s: float = 1.0
    worker_lease_s: int = 30
    end_timeout_s: float = 5.0
    caller: Literal["pipecat", "stub"] = "pipecat"
    deepgram_api_key: SecretStr | None = Field(default=None, validation_alias="DEEPGRAM_API_KEY")
    deepgram_url: str = ""
    elevenlabs_api_key: SecretStr | None = Field(
        default=None, validation_alias="ELEVENLABS_API_KEY"
    )
    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"
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

    # Required fields come from the environment; without this pyright demands them as arguments.
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
