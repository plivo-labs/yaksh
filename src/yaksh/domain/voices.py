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

from yaksh.domain.languages import INDIAN_AND_ENGLISH, INDIAN_ENGLISH_AND_SPANISH, Language

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
class TtsModel:
    """A text-to-speech model that a voice can use."""

    id: str | None
    """None for a provider without a model choice: Azure's voice name carries its model, and
    Nimble has one."""
    label: str
    speed: tuple[float, float]
    """The range of the speed or pace; 1.0 is the voice's natural pace."""
    languages: frozenset[Language]
    """The languages of Yaksh's that the model can speak."""


@dataclass(frozen=True)
class TtsTraits:
    label: str
    word_timestamps: bool
    """False: the provider times whole sentences, so a cut-off reply is cut at a sentence."""
    lookup: bool
    """The provider describes a voice by its ID; otherwise the person enters the details."""
    models: tuple[TtsModel, ...]
    """The models a voice can use; a new voice gets the first."""

    @property
    def speed(self) -> tuple[float, float]:
        """The widest speed any model takes, for a voice whose model is not known here."""
        return min(model.speed[0] for model in self.models), max(m.speed[1] for m in self.models)

    @property
    def languages(self) -> frozenset[Language]:
        return frozenset().union(*(model.languages for model in self.models))

    def chosen(self, model_id: str | None) -> TtsModel:
        """The model, or the first for none. Raises ValueError for a model that is not in
        Yaksh's list for the provider."""
        if model_id is None:
            return self.models[0]
        found = next((model for model in self.models if model.id == model_id), None)
        if found is None:
            names = ", ".join(model.id for model in self.models if model.id is not None)
            raise ValueError(
                f"{self.label} has no model {model_id}" + (f"; use one of {names}" if names else "")
            )
        return found

    def name_of(self, model: TtsModel) -> str:
        return f"{self.label} {model.label}" if model.id is not None else self.label


TTS = {
    # Flash and Multilingual take no language setting for Bengali, Gujarati, Kannada, Marathi and
    # Telugu and read them from the text. v3 and v4 take every language, but no speed.
    VoiceProvider.ELEVENLABS: TtsTraits(
        "ElevenLabs",
        word_timestamps=True,
        lookup=True,
        models=(
            TtsModel("eleven_flash_v2_5", "Flash v2.5", (0.7, 1.2), INDIAN_ENGLISH_AND_SPANISH),
            TtsModel(
                "eleven_multilingual_v2", "Multilingual v2", (0.7, 1.2), INDIAN_ENGLISH_AND_SPANISH
            ),
            TtsModel("eleven_v4_turbo", "v4 Turbo", (1.0, 1.0), INDIAN_ENGLISH_AND_SPANISH),
            TtsModel("eleven_v4", "v4", (1.0, 1.0), INDIAN_ENGLISH_AND_SPANISH),
            TtsModel("eleven_v3", "v3", (1.0, 1.0), INDIAN_ENGLISH_AND_SPANISH),
            TtsModel(
                "eleven_v3_conversational",
                "v3 Conversational",
                (1.0, 1.0),
                INDIAN_ENGLISH_AND_SPANISH,
            ),
        ),
    ),
    VoiceProvider.CARTESIA: TtsTraits(
        "Cartesia",
        word_timestamps=True,
        lookup=False,
        models=tuple(
            TtsModel(model_id, label, (0.6, 1.5), INDIAN_ENGLISH_AND_SPANISH)
            for model_id, label in (
                ("sonic-3.6", "Sonic 3.6"),
                ("sonic-3.5", "Sonic 3.5"),
                ("sonic-3", "Sonic 3"),
            )
        ),
    ),
    VoiceProvider.SARVAM: TtsTraits(
        "Sarvam",
        word_timestamps=False,
        lookup=False,
        models=(
            TtsModel("bulbul:v4-flash", "Bulbul v4 Flash", (0.5, 2.0), INDIAN_AND_ENGLISH),
            TtsModel("bulbul:v3", "Bulbul v3", (0.5, 2.0), INDIAN_AND_ENGLISH),
        ),
    ),
    VoiceProvider.AZURE: TtsTraits(
        "Azure",
        word_timestamps=True,
        lookup=False,
        models=(TtsModel(None, "Azure", (0.5, 2.0), INDIAN_ENGLISH_AND_SPANISH),),
    ),
    VoiceProvider.NIMBLE: TtsTraits(
        "Nimble",
        word_timestamps=True,
        lookup=True,
        models=(TtsModel(None, "Nimble", (0.7, 1.0), INDIAN_AND_ENGLISH),),
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
    model: str | None = None
    """The provider's model; None for a provider without a model choice, and for a voice read
    from stored JSON, which never holds it: an older process refuses an unknown field, so the
    model lives in its own columns."""

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
        cls,
        provider: VoiceProvider,
        voice_id: str,
        model: str | None,
        speed: float,
        stability: float | None,
    ) -> VoiceSettings:
        """A voice with the speed brought into its model's range, and the stability only where
        the provider has it: for a voice that changes provider or model."""
        low, high = provider.traits.chosen(model).speed
        return cls(
            provider=provider,
            id=voice_id,
            model=model,
            speed=min(max(speed, low), high),
            stability=stability if provider is VoiceProvider.ELEVENLABS else None,
        )

    @property
    def model_in_use(self) -> TtsModel:
        """The voice's model, or the provider's first for a voice without one. Raises
        ValueError for a model that is not in Yaksh's list."""
        return self.provider.traits.chosen(self.model)

    @model_validator(mode="after")
    def provider_settings(self) -> Self:
        """The speed must fit the model. A model outside Yaksh's list is refused only where a
        voice is chosen, so a stored voice still reads after a later release drops its model;
        until then its speed is held to the widest range of the provider."""
        traits = self.provider.traits
        model = next((m for m in traits.models if self.model and m.id == self.model), None)
        low, high = model.speed if model else traits.speed
        if not low <= self.speed <= high:
            allowed = f"only speed {low:g}" if low == high else f"a speed from {low:g} to {high:g}"
            raise ValueError(f"{traits.name_of(model) if model else traits.label} takes {allowed}")
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
    model: str | None = None
    """The provider's first model when left out."""

    @model_validator(mode="after")
    def provider_rules(self) -> Self:
        if not self.provider.traits.lookup and self.name is None:
            raise ValueError(f"{self.provider.label} has no voice lookup: give the voice a name")
        check_spoken(self.provider, self.model_in_use, self.languages)
        return self

    @property
    def model_in_use(self) -> TtsModel:
        return self.provider.traits.chosen(self.model)


def check_spoken(provider: VoiceProvider, model: TtsModel, languages: frozenset[Language]) -> None:
    unspoken = sorted(languages - model.languages)
    if unspoken:
        names = ", ".join(language.label for language in unspoken)
        raise ValueError(f"{provider.traits.name_of(model)} does not speak {names}")


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
