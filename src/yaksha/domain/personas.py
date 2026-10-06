from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from yaksha.domain.background_noise import BackgroundNoise
from yaksha.domain.languages import Language
from yaksha.domain.voices import VoiceGender, VoiceSettings


class PersonaSettings(BaseModel):
    """How the caller talks and sounds, as a client sets it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str = Field(min_length=1, max_length=4000)
    language: Language = Language.EN
    voice: VoiceSettings
    background_noise: BackgroundNoise = BackgroundNoise()


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
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    language: Language | None = None
    voice: VoiceSettings | None = None
    background_noise: BackgroundNoise | None = None

    @field_validator("name", "prompt", "language", "voice", "background_noise")
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
