import uuid
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from yaksh.domain.answering import Answering
from yaksh.domain.languages import Language
from yaksh.domain.surroundings import Surroundings
from yaksh.domain.voices import SampleLine, VoiceGender, VoiceSettings

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class PersonaSettings(BaseModel):
    """How the caller talks and sounds, as a client sets it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: Prompt
    language: Language = Language.EN
    """The primary language: the caller's main one, which Yaksh's own lines also use."""
    additional_languages: tuple[Language, ...] = Field(default=(), max_length=8)
    """Languages the caller can switch to during a call; empty for a caller of one language."""
    voice: VoiceSettings
    surroundings: Surroundings = Surroundings()
    sample_line: SampleLine | None = None
    """What the persona's previews say; None says its language's sample sentence."""
    answering: Answering = Answering()

    @property
    def languages(self) -> tuple[Language, ...]:
        """Every language the caller speaks, the primary first."""
        return (self.language, *self.additional_languages)

    @model_validator(mode="after")
    def languages_are_distinct(self) -> Self:
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("additional languages must differ from each other and from language")
        return self


class PersonaConfig(PersonaSettings):
    """What a persona version pins: the settings plus the voice gender from the voices list."""

    voice_gender: VoiceGender | None = None

    def stored(self) -> dict[str, Any]:
        """The config as a version keeps it, without the voice's model, which has its own
        column. With no additional languages it has no `additional_languages` key: a process of
        an older version refuses a field that it does not know, and it must still read the
        version during a rolling deploy."""
        exclude: dict[str, Any] = {"voice": {"model"}}
        if not self.additional_languages:
            exclude["additional_languages"] = True
        return self.model_dump(mode="json", exclude=exclude)


class PersonaCreate(PersonaSettings):
    name: str = Field(min_length=1, max_length=80)
    forked_from_id: uuid.UUID | None = None
    """The persona this one was copied from."""

    def settings(self) -> PersonaSettings:
        return PersonaSettings.model_validate(self.model_dump(exclude={"name", "forked_from_id"}))


class PersonaIdea(BaseModel):
    """A short line about the caller, such as "angry senior woman on a noisy street"."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idea: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PersonaDraft(BaseModel):
    """A new persona's fields written from a short line, for the person to check before they
    save it. The console picks a voice of `voice_gender` in the language."""

    name: str
    prompt: str
    language: Language
    voice_gender: VoiceGender
    speed: float
    surroundings: Surroundings
    left_out: list[str]
    """Parts of the line that no field can hold, each with the reason, for the person to see."""


class PersonaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, min_length=1, max_length=80)
    prompt: Prompt | None = None
    language: Language | None = None
    additional_languages: tuple[Language, ...] | None = Field(default=None, max_length=8)
    """An empty list clears them."""
    voice: VoiceSettings | None = None
    surroundings: Surroundings | None = None
    sample_line: SampleLine | None = None
    """None clears it."""
    answering: Answering | None = None

    @field_validator(
        "name",
        "prompt",
        "language",
        "additional_languages",
        "voice",
        "surroundings",
        "answering",
    )
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
