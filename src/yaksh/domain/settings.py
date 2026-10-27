"""The settings a user changes on the Settings page. The database holds the values someone
changed; every other value is the default here, so a release can change a default. A process
reads them again whenever their version changes, so a change needs no restart."""

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

from yaksh.domain.speech import SttProvider
from yaksh.domain.voices import VoiceProvider

TRIGGER_SECRET_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

Url = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^https?://\S+$")]
Address = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(https?|wss?)://\S+$")]
"""The address of a speech provider: an HTTP or a websocket URL."""
AzureRegion = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9]{2,40}$")]
"""An Azure region, such as centralindia, which names the Speech resource's address."""
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Effort = Annotated[str, StringConstraints(pattern=r"^[a-z]{1,20}$")]
ApplicationId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{1,40}$")]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Llm(Section):
    """Any API with OpenAI's Responses endpoint. The caller, scenario writing and the judges
    use it."""

    base_url: Url = "https://api.openai.com/v1"


class Speech(Section):
    stt: SttProvider = SttProvider.DEEPGRAM
    """The provider that hears the agent on every call."""


class Deepgram(Section):
    base_url: Url = "https://api.deepgram.com"
    model: ModelName = "nova-3"


class SarvamStt(Section):
    """Sarvam's speech-to-text host is fixed by its SDK, so it has no address."""

    model: ModelName = "saaras:v4"


class AssemblyAI(Section):
    url: Address = "wss://streaming.assemblyai.com/v3/ws"
    model: ModelName = "universal-3-6-pro"


class Soniox(Section):
    url: Address = "wss://stt-rt.soniox.com/transcribe-websocket"
    model: ModelName = "stt-rt-v5"


class Gladia(Section):
    url: Address = "https://api.gladia.io/v2/live"
    model: ModelName = "solaria-1"


class ElevenLabs(Section):
    url: Address = "wss://api.elevenlabs.io"
    """A data residency address, such as wss://api.eu.residency.elevenlabs.io, keeps the speech
    in that region."""
    model: ModelName = "eleven_flash_v2_5"


class Cartesia(Section):
    url: Address = "wss://api.cartesia.ai/tts/websocket"
    model: ModelName = "sonic-3.6"


class SarvamTts(Section):
    base_url: Address = "https://api.sarvam.ai"
    model: ModelName = "bulbul:v4-flash"
    """bulbul:v4-flash and bulbul:v3 name their speakers differently."""


class Azure(Section):
    region: AzureRegion = "eastus"


class CallerModel(Section):
    model: ModelName = "gpt-6-luna"
    reasoning_effort: Effort | None = None
    """None sends low, or the model's lowest effort when that is higher, to a model that Pipecat
    lists, and no effort to other models: a model without reasoning refuses any value."""


class GenerationModel(Section):
    model: ModelName | None = None
    """The caller's model when None."""
    reasoning_effort: Effort | None = "max"
    timeout_s: float = Field(default=300.0, gt=0, le=3600)
    """One model request while writing scenarios; high effort takes minutes."""


class BriefModel(Section):
    """The model that drafts an agent's brief from its config while the person waits."""

    model: ModelName = "gpt-6-luna"
    reasoning_effort: Effort | None = "low"
    timeout_s: float = Field(default=60.0, gt=0, le=3600)


class JudgeModel(Section):
    model: ModelName = "gpt-6-luna"
    reasoning_effort: Effort | None = "medium"
    timeout_s: float = Field(default=60.0, gt=0, le=3600)
    sources_timeout_s: float = Field(default=180.0, gt=0, le=3600)
    """One request of the judges that read the agent's whole instructions or documents."""
    max_output_tokens: int = Field(default=8000, gt=0, le=200_000)
    """Reasoning tokens count too."""
    max_input_chars: int = Field(default=400_000, gt=0, le=10_000_000)
    """The most text one judge request holds; larger sources make that judge's item an error."""
    jev_pass_bar: float = Field(default=0.95, gt=0, le=1)
    """How sure Jev must be that an item is met to publish it as a pass."""


class EvaluationLimits(Section):
    """How much one evaluator does at once, within the LLM provider's rate limits."""

    evaluations_at_once: int = Field(default=2, ge=1, le=32)
    judge_calls_at_once: int = Field(default=8, ge=1, le=64)
    """Judge model calls in flight across one evaluator's evaluations."""


class WorkerLimits(Section):
    phone_conversations_at_once: int = Field(default=4, ge=1, le=50)
    text_conversations_at_once: int = Field(default=20, ge=1, le=100)


class Audit(Section):
    sample_rate: float = Field(default=0.1, ge=0, le=1)
    """The share of judged calls in the audit lane, chosen by a hash of the conversation id."""
    weekly_budget: int = Field(default=30, ge=0, le=10_000)
    """The most audit conversations the review queue offers for one week of calls."""


class Phone(Section):
    ring_timeout_s: int = Field(default=30, ge=1, le=300)
    number_rest_s: int = Field(default=300, ge=0, le=86_400)
    """How long a released number waits before a new test may use it, so a late call from an
    earlier test does not reach the next one."""
    timezone: str = "UTC"
    """The zone of the date the caller is told is today; a run takes it when it starts."""
    application_id: ApplicationId | None = None
    """The Plivo application that receives the calls of the test numbers. A number linked to it
    is a test number; without it Yaksh has no numbers."""
    refresh_interval_s: int = Field(default=300, ge=60, le=86_400)
    """How often a worker reads the numbers of the Plivo account again, to see changes made in
    the Plivo console."""

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown time zone: {value}") from error
        return value


MAX_DATA_SETS = 50
"""The ceiling of the operator's limit on data sets per scenario."""


class Limits(Section):
    default_max_turns: int = Field(default=20, ge=1, le=100)
    """How many agent turns the caller answers before it says goodbye, when a run does not
    say."""
    default_max_duration_s: int = Field(default=300, ge=10, le=1800)
    """The same bounds as a run's own max_duration_s."""
    max_run_conversations: int = Field(default=200, ge=1, le=10_000)
    """Conversations one run starts, the scenarios times the repeats. Retries are not counted."""
    max_run_repeats: int = Field(default=10, ge=1, le=1000)
    max_run_retries: int = Field(default=3, ge=0, le=100)
    max_run_start_interval_s: int = Field(default=600, ge=1, le=86_400)
    max_scenario_data_sets: int = Field(default=10, ge=1, le=MAX_DATA_SETS)
    """Conversations one suite run starts, over all its runs. Retries are not counted. The
    default is 100 entries of the default run limit."""

    @property
    def default_max_retries(self) -> int:
        """The retries of a run that does not set them: 1, or the limit when lower."""
        return min(1, self.max_run_retries)


class SecretName(StrEnum):
    LLM_API_KEY = "llm_api_key"
    DEEPGRAM_API_KEY = "deepgram_api_key"
    SARVAM_API_KEY = "sarvam_api_key"
    ASSEMBLYAI_API_KEY = "assemblyai_api_key"
    SONIOX_API_KEY = "soniox_api_key"
    GLADIA_API_KEY = "gladia_api_key"
    ELEVENLABS_API_KEY = "elevenlabs_api_key"
    CARTESIA_API_KEY = "cartesia_api_key"
    AZURE_API_KEY = "azure_api_key"
    TYPESAFE_API_KEY = "typesafe_api_key"
    """Jev, TypeSafe's classifier, answers criteria and agent rules before the judges; call
    transcripts are sent to TypeSafe."""
    PLIVO_AUTH_ID = "plivo_auth_id"
    PLIVO_AUTH_TOKEN = "plivo_auth_token"
    TRIGGER_SIGNING_KEY = "trigger_signing_key"
    """Signs every outbound agent trigger so its receiver can check it came from Yaksh."""


TRIGGER_SECRET = "trigger:"
"""The stored name of a trigger secret is this prefix and its name."""


def check_trigger_secret_name(name: str) -> str:
    if not TRIGGER_SECRET_NAME.fullmatch(name):
        raise ValueError(
            f"trigger secret {name!r}: use capital letters, digits and _, starting with a letter"
        )
    return name


class Secrets(Section):
    """The keys, each stored encrypted. The API never returns one."""

    llm_api_key: SecretStr | None = None
    deepgram_api_key: SecretStr | None = None
    sarvam_api_key: SecretStr | None = None
    assemblyai_api_key: SecretStr | None = None
    soniox_api_key: SecretStr | None = None
    gladia_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    cartesia_api_key: SecretStr | None = None
    azure_api_key: SecretStr | None = None
    typesafe_api_key: SecretStr | None = None
    plivo_auth_id: SecretStr | None = None
    plivo_auth_token: SecretStr | None = None
    trigger_signing_key: SecretStr | None = None
    triggers: dict[str, SecretStr] = {}
    """Values a trigger template names as {{secrets.NAME}}."""

    @field_validator("triggers")
    @classmethod
    def trigger_names(cls, triggers: dict[str, SecretStr]) -> dict[str, SecretStr]:
        for name in triggers:
            check_trigger_secret_name(name)
        return triggers

    def flat(self) -> dict[str, str]:
        """Every saved secret by its stored name: a SecretName, or TRIGGER_SECRET and the
        name of a trigger secret."""
        named = {
            name.value: secret.get_secret_value()
            for name in SecretName
            if (secret := getattr(self, name.value)) is not None
        }
        return named | {
            TRIGGER_SECRET + name: secret.get_secret_value()
            for name, secret in self.triggers.items()
        }

    @classmethod
    def from_flat(cls, flat: Mapping[str, str]) -> Secrets:
        return cls.model_validate(
            {name: value for name, value in flat.items() if not name.startswith(TRIGGER_SECRET)}
            | {
                "triggers": {
                    name.removeprefix(TRIGGER_SECRET): value
                    for name, value in flat.items()
                    if name.startswith(TRIGGER_SECRET)
                }
            }
        )


def reveal(secret: SecretStr | None) -> str | None:
    return None if secret is None else secret.get_secret_value()


def is_secret_name(name: str) -> bool:
    if name in {secret.value for secret in SecretName}:
        return True
    return name.startswith(TRIGGER_SECRET) and bool(
        TRIGGER_SECRET_NAME.fullmatch(name.removeprefix(TRIGGER_SECRET))
    )


KEY_URLS = {
    SecretName.LLM_API_KEY: ("llm", "base_url"),
    SecretName.DEEPGRAM_API_KEY: ("deepgram", "base_url"),
    SecretName.ASSEMBLYAI_API_KEY: ("assemblyai", "url"),
    SecretName.SONIOX_API_KEY: ("soniox", "url"),
    SecretName.GLADIA_API_KEY: ("gladia", "url"),
    SecretName.SARVAM_API_KEY: ("sarvam_tts", "base_url"),
    SecretName.ELEVENLABS_API_KEY: ("elevenlabs", "url"),
    SecretName.CARTESIA_API_KEY: ("cartesia", "url"),
    SecretName.AZURE_API_KEY: ("azure", "region"),
}
"""The address each key is sent to. A new address removes the key, unless the same change
saves a key for it: the key goes only where it was checked."""

STT_KEYS = {
    SttProvider.DEEPGRAM: SecretName.DEEPGRAM_API_KEY,
    SttProvider.SARVAM: SecretName.SARVAM_API_KEY,
    SttProvider.ASSEMBLYAI: SecretName.ASSEMBLYAI_API_KEY,
    SttProvider.SONIOX: SecretName.SONIOX_API_KEY,
    SttProvider.GLADIA: SecretName.GLADIA_API_KEY,
}
TTS_KEYS = {
    VoiceProvider.ELEVENLABS: SecretName.ELEVENLABS_API_KEY,
    VoiceProvider.CARTESIA: SecretName.CARTESIA_API_KEY,
    VoiceProvider.SARVAM: SecretName.SARVAM_API_KEY,
    VoiceProvider.AZURE: SecretName.AZURE_API_KEY,
}


class SettingsValues(Section):
    """Every setting that is not a secret."""

    llm: Llm = Llm()
    speech: Speech = Speech()
    deepgram: Deepgram = Deepgram()
    sarvam_stt: SarvamStt = SarvamStt()
    assemblyai: AssemblyAI = AssemblyAI()
    soniox: Soniox = Soniox()
    gladia: Gladia = Gladia()
    elevenlabs: ElevenLabs = ElevenLabs()
    cartesia: Cartesia = Cartesia()
    sarvam_tts: SarvamTts = SarvamTts()
    azure: Azure = Azure()
    caller: CallerModel = CallerModel()
    generation: GenerationModel = GenerationModel()
    brief: BriefModel = BriefModel()
    judges: JudgeModel = JudgeModel()
    evaluation: EvaluationLimits = EvaluationLimits()
    worker: WorkerLimits = WorkerLimits()
    audit: Audit = Audit()
    phone: Phone = Phone()
    limits: Limits = Limits()


class AppSettings(SettingsValues):
    version: int = 0
    """Grows with every change; a process that has read this version holds current settings."""
    secrets: Secrets = Secrets()

    @property
    def generation_model(self) -> str:
        return self.generation.model or self.caller.model

    @property
    def missing_caller_keys(self) -> list[str]:
        """The keys every call needs that are not saved, by the names Settings shows. The key
        of a persona's voice is checked when a run starts."""
        return [
            name
            for name, key in (
                ("LLM provider", self.secrets.llm_api_key),
                (self.speech.stt.label, self.stt_key),
            )
            if key is None
        ]

    def tts_key(self, provider: VoiceProvider) -> SecretStr | None:
        return getattr(self.secrets, TTS_KEYS[provider].value)

    @property
    def stt_key(self) -> SecretStr | None:
        """The key of the speech-to-text provider in use."""
        return getattr(self.secrets, STT_KEYS[self.speech.stt].value)

    @property
    def plivo_credentials(self) -> tuple[str, str] | None:
        auth_id, token = self.secrets.plivo_auth_id, self.secrets.plivo_auth_token
        if auth_id is None or token is None:
            return None
        return auth_id.get_secret_value(), token.get_secret_value()
