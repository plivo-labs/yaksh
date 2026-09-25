from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)


class Language(StrEnum):
    EN = "en"
    HI = "hi"
    HINGLISH = "hinglish"


class VoiceProvider(StrEnum):
    ELEVENLABS = "elevenlabs"


class Voice(BaseModel):
    """A voice of one text-to-speech provider and how it speaks; the id means nothing
    outside that provider. The id goes into provider URLs, so dots and slashes are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: VoiceProvider
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    stability: float = Field(default=0.5, ge=0.0, le=1.0)


class PersonaConfig(BaseModel):
    """What a persona version pins: how the caller talks and sounds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str = Field(min_length=1, max_length=4000)
    language: Language = Language.EN
    voice: Voice


class PersonaCreate(PersonaConfig):
    name: str = Field(min_length=1, max_length=80)

    def config(self) -> PersonaConfig:
        return PersonaConfig.model_validate(self.model_dump(exclude={"name"}))


class PersonaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, min_length=1, max_length=80)
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    language: Language | None = None
    voice: Voice | None = None

    @field_validator("name", "prompt", "language", "voice")
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
