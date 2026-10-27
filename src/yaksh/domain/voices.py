from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from yaksh.domain.languages import Language

PROVIDER_VOICE_ID = r"^[A-Za-z0-9_-]+$"


class VoiceProvider(StrEnum):
    """A text-to-speech provider that voices personas."""

    ELEVENLABS = "elevenlabs"
    CARTESIA = "cartesia"
    SARVAM = "sarvam"
    AZURE = "azure"
    NIMBLE = "nimble"

    @property
    def label(self) -> str:
        return TTS[self].label

    @property
    def traits(self) -> TtsTraits:
        return TTS[self]


@dataclass(frozen=True)
class TtsTraits:
    label: str
    speed: tuple[float, float]
    """The range of the provider's speed or pace; 1.0 is the voice's natural pace."""
    word_timestamps: bool
    """False: the provider times whole sentences, so a cut-off reply is cut at a sentence."""
    lookup: bool
    """The provider describes a voice by its ID; otherwise the person enters the details."""
    languages: frozenset[Language] = frozenset(Language)
    """The languages of Yaksh's that the provider can speak."""


INDIAN_AND_ENGLISH = frozenset(Language) - {Language.ES}
TTS = {
    VoiceProvider.ELEVENLABS: TtsTraits(
        "ElevenLabs", (0.7, 1.2), word_timestamps=True, lookup=True
    ),
    VoiceProvider.CARTESIA: TtsTraits("Cartesia", (0.6, 1.5), word_timestamps=True, lookup=False),
    VoiceProvider.SARVAM: TtsTraits(
        "Sarvam", (0.5, 2.0), word_timestamps=False, lookup=False, languages=INDIAN_AND_ENGLISH
    ),
    VoiceProvider.AZURE: TtsTraits("Azure", (0.5, 2.0), word_timestamps=True, lookup=False),
    VoiceProvider.NIMBLE: TtsTraits(
        "Nimble", (0.7, 1.0), word_timestamps=True, lookup=True, languages=INDIAN_AND_ENGLISH
    ),
}


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
    speed: float = 1.0
    """The provider's speed or pace, within its range."""
    stability: float | None = Field(default=None, ge=0.0, le=1.0)
    """ElevenLabs only, where it defaults to 0.5."""

    @model_validator(mode="before")
    @classmethod
    def elevenlabs_stability(cls, data: Any) -> Any:
        if (
            isinstance(data, dict)
            and data.get("provider") == VoiceProvider.ELEVENLABS
            and data.get("stability") is None
        ):
            return {**data, "stability": 0.5}
        return data

    @classmethod
    def fitted(
        cls, provider: VoiceProvider, voice_id: str, speed: float, stability: float | None
    ) -> VoiceSettings:
        """A voice with the speed brought into the provider's range, and the stability only
        where the provider has it: for a voice that changes provider."""
        low, high = provider.traits.speed
        return cls(
            provider=provider,
            id=voice_id,
            speed=min(max(speed, low), high),
            stability=stability if provider is VoiceProvider.ELEVENLABS else None,
        )

    @model_validator(mode="after")
    def provider_settings(self) -> Self:
        low, high = self.provider.traits.speed
        if not low <= self.speed <= high:
            raise ValueError(f"{self.provider.label} takes a speed from {low} to {high}")
        if self.provider is not VoiceProvider.ELEVENLABS and self.stability is not None:
            raise ValueError(f"{self.provider.label} has no stability setting")
        return self


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
    """A voice to add. A provider with lookup fills the details it has; for any other, the
    name is required and the gender and accent come from here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: VoiceProvider
    provider_voice_id: str = Field(pattern=PROVIDER_VOICE_ID)
    languages: frozenset[Language] = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    gender: VoiceGender | None = None
    accent: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def provider_rules(self) -> Self:
        if not self.provider.traits.lookup and self.name is None:
            raise ValueError(f"{self.provider.label} has no voice lookup: give the voice a name")
        check_spoken(self.provider, self.languages)
        return self


def check_spoken(provider: VoiceProvider, languages: frozenset[Language]) -> None:
    unspoken = sorted(languages - provider.traits.languages)
    if unspoken:
        names = ", ".join(language.label for language in unspoken)
        raise ValueError(f"{provider.label} does not speak {names}")


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
    async def get_voice(self, voice_id: str) -> ProviderVoice | None:
        """None when the account does not have the voice; only for a provider with lookup."""
        ...

    async def speak(self, voice: VoiceSettings, language: Language, text: str) -> bytes:
        """The text spoken through the same text-to-speech as a call, in its 8 kHz format, as
        WAV. Raises UnavailableError with the provider's reason, such as an unknown voice."""
        ...
