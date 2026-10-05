from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from truman.domain.numbers import E164

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
    default_max_turns: int = Field(default=20, ge=1, le=100)
    """How many agent turns the caller answers before it says goodbye, when a request does not
    say."""
    max_run_conversations: int = Field(default=200, ge=1)
    """Conversations one run starts, the scenarios times the repeats. Retries are not counted."""
    max_run_repeats: int = Field(default=10, ge=1)
    max_run_retries: int = Field(default=3, ge=0)
    max_run_start_interval_s: int = Field(default=600, ge=1)
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
    deepgram_api_key: SecretStr | None = Field(default=None, validation_alias="DEEPGRAM_API_KEY")
    deepgram_base_url: str = Field(
        default="https://api.deepgram.com", validation_alias="DEEPGRAM_BASE_URL"
    )
    deepgram_model: str = "nova-3"
    elevenlabs_api_key: SecretStr | None = Field(
        default=None, validation_alias="ELEVENLABS_API_KEY"
    )
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL"
    )
    persona_llm_model: str = Field(default="gpt-4.1", validation_alias="PERSONA_LLM_MODEL")
    persona_llm_reasoning_effort: str | None = Field(
        default=None, validation_alias="PERSONA_LLM_REASONING_EFFORT"
    )
    """Sent with every caller turn when set. Unset, a reasoning model that accepts none is asked
    for it, and other models get no effort; a model without reasoning refuses any value."""
    generation_llm_model: str | None = Field(default=None, validation_alias="GENERATION_LLM_MODEL")
    """The model that writes test scenarios; the persona model when unset."""
    generation_llm_reasoning_effort: str = Field(
        default="max", validation_alias="GENERATION_LLM_REASONING_EFFORT"
    )
    """Sent with every generation call when the model takes it."""
    generation_llm_timeout_s: float = Field(
        default=300.0, gt=0, validation_alias="GENERATION_LLM_TIMEOUT_S"
    )
    """One model call while writing scenarios; high reasoning effort takes minutes."""
    judge_llm_model: str = Field(default="gpt-6-luna", validation_alias="JUDGE_LLM_MODEL")
    """The model that judges calls; empty turns the judges off."""
    judge_llm_reasoning_effort: str | None = Field(
        default="medium", validation_alias="JUDGE_LLM_REASONING_EFFORT"
    )
    judge_llm_timeout_s: float = Field(default=60.0, gt=0, validation_alias="JUDGE_LLM_TIMEOUT_S")
    judge_max_output_tokens: int = Field(
        default=8000, gt=0, validation_alias="JUDGE_MAX_OUTPUT_TOKENS"
    )
    """Reasoning tokens count too."""
    typesafe_api_key: SecretStr | None = Field(default=None, validation_alias="TYPESAFE_API_KEY")
    """Optional. Jev, TypeSafe's classifier, answers criteria and agent rules first; call
    transcripts are sent to TypeSafe."""
    jev_pass_bar: float = Field(default=0.95, gt=0, le=1, validation_alias="JEV_PASS_BAR")
    """How sure Jev must be that an item is met to publish it as a pass."""
    judge_sources_timeout_s: float = Field(
        default=180.0, gt=0, validation_alias="JUDGE_SOURCES_TIMEOUT_S"
    )
    """One request of the judges that read the agent's whole instructions or documents."""
    judge_max_input_chars: int = Field(
        default=400_000, gt=0, validation_alias="JUDGE_MAX_INPUT_CHARS"
    )
    """The most text one judge request holds: the call with the agent's instructions or its
    documents. Larger sources make that judge's item an error."""
    judge_openai_api_key: SecretStr | None = Field(
        default=None, validation_alias="JUDGE_OPENAI_API_KEY"
    )
    """The judge model's key and address; the caller's OpenAI settings when unset."""
    judge_openai_base_url: str | None = Field(
        default=None, validation_alias="JUDGE_OPENAI_BASE_URL"
    )
    plivo_auth_id: SecretStr | None = Field(default=None, validation_alias="PLIVO_AUTH_ID")
    plivo_auth_token: SecretStr | None = Field(default=None, validation_alias="PLIVO_AUTH_TOKEN")
    plivo_numbers: Annotated[list[E164], NoDecode] = []
    plivo_app_id: str | None = None
    """The Plivo Application that sends outbound test calls to this worker."""
    webhook_signing_key: SecretStr | None = None
    """Signs every outbound agent trigger so its receiver can check it came from Truman."""
    allow_private_triggers: bool = False
    """Allow trigger URLs on private or local addresses, for development."""
    number_rest_s: int = Field(default=300, ge=0)
    """How long a released number waits before a new test may use it, so a late call from an
    earlier test does not reach the next one."""
    public_url: str | None = None
    stream_port: int = 8770
    ring_timeout_s: int = 30
    s3_endpoint: str | None = None
    """Where uploaded files are kept: any S3-compatible service. Uploads are off without it."""
    s3_bucket: str = "truman"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str = "us-east-1"
    timezone: str = "UTC"
    """The zone of the date the caller is told is today."""

    @property
    def default_max_retries(self) -> int:
        """The retries of a run that does not set them: 1, or the operator's limit when lower."""
        return min(1, self.max_run_retries)

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
