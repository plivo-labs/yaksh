from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from yaksha.domain.languages import Language
from yaksha.domain.surroundings import Surroundings
from yaksha.domain.voices import SampleLine, VoiceGender, VoiceSettings

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class PersonaSettings(BaseModel):
    """How the caller talks and sounds, as a client sets it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: Prompt
    language: Language = Language.EN
    voice: VoiceSettings
    surroundings: Surroundings = Surroundings()
    sample_line: SampleLine | None = None
    """What the persona's previews say; None says its language's sample sentence."""


class PersonaConfig(PersonaSettings):
    """What a persona version pins: the settings plus the voice gender from the voices list."""

    voice_gender: VoiceGender | None = None


class PersonaCreate(PersonaSettings):
    name: str = Field(min_length=1, max_length=80)

    def settings(self) -> PersonaSettings:
        return PersonaSettings.model_validate(self.model_dump(exclude={"name"}))


class PersonaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, min_length=1, max_length=80)
    prompt: Prompt | None = None
    language: Language | None = None
    voice: VoiceSettings | None = None
    surroundings: Surroundings | None = None
    sample_line: SampleLine | None = None
    """None clears it."""

    @field_validator("name", "prompt", "language", "voice", "surroundings")
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
