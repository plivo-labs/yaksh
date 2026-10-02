from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class NoiseSound(StrEnum):
    NONE = "none"
    STREET = "street"
    CAFE = "cafe"
    OFFICE = "office"
    CAR = "car"
    TV = "tv"
    CROWD = "crowd"
    KITCHEN = "kitchen"
    WIND = "wind"


class NoiseLevel(StrEnum):
    """How loud the background is, as the caller's speech level above the noise."""

    LIGHT = "light"
    BUSY = "busy"
    LOUD = "loud"


class BackgroundNoise(BaseModel):
    """The sound behind the caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sound: NoiseSound = NoiseSound.NONE
    level: NoiseLevel = NoiseLevel.BUSY

    @model_validator(mode="before")
    @classmethod
    def one_form_of_none(cls, data: Any) -> Any:
        """No noise has one form, so it gives one persona version and one request hash."""
        if isinstance(data, dict) and data.get("sound") == NoiseSound.NONE:
            return {**data, "level": NoiseLevel.BUSY}
        return data
