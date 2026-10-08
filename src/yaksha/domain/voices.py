from enum import StrEnum
from typing import Annotated, Any, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from yaksha.domain.languages import Language

PROVIDER_VOICE_ID = r"^[A-Za-z0-9_-]+$"


class VoiceProvider(StrEnum):
    ELEVENLABS = "elevenlabs"

    @property
    def label(self) -> str:
        match self:
            case VoiceProvider.ELEVENLABS:
                return "ElevenLabs"


class VoiceGender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


class VoiceSettings(BaseModel):
    """A voice of one text-to-speech provider and how it speaks; the id means nothing
    outside that provider. The id goes into provider URLs, so dots and slashes are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: VoiceProvider
    id: str = Field(pattern=PROVIDER_VOICE_ID)
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    stability: float = Field(default=0.5, ge=0.0, le=1.0)


class ProviderVoice(BaseModel):
    """A voice as its provider describes it. `listed_languages` are the languages the provider
    lists for the voice in any model; the model decides what the voice can really speak."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    gender: VoiceGender | None = None
    accent: str | None = None
    listed_languages: tuple[Language, ...] = ()


class VoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: VoiceProvider
    provider_voice_id: str = Field(pattern=PROVIDER_VOICE_ID)
    languages: frozenset[Language] = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)


class VoiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, min_length=1, max_length=80)
    languages: frozenset[Language] | None = Field(default=None, min_length=1)

    @field_validator("name", "languages")
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


SampleLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
"""What a preview says in a voice; calls never use it."""


class VoicePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    voice: VoiceSettings
    language: Language
    sample_line: SampleLine | None = None
    """None says the language's sample sentence."""


class VoiceClient(Protocol):
    async def get_voice(self, voice_id: str) -> ProviderVoice | None: ...

    async def speak(self, voice: VoiceSettings, language: Language, text: str) -> bytes | None:
        """The text spoken with the call's model, voice settings and 8 kHz format, as WAV; None
        when the voice is unknown."""
        ...
