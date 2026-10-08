from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MIN_DB = -30
MAX_DB = 10
Decibels = Field(ge=MIN_DB, le=MAX_DB)
"""A level relative to the caller's speech: 0 is as loud as the caller."""


class NoiseSound(StrEnum):
    STREET = "street"
    CAFE = "cafe"
    OFFICE = "office"
    CAR = "car"
    TV = "tv"
    CROWD = "crowd"
    KITCHEN = "kitchen"
    WIND = "wind"


class SpeakerKind(StrEnum):
    """What the person behind the caller does."""

    TALKS_TO_CALLER = "talks_to_caller"
    OWN_PHONE_CALL = "own_phone_call"
    TV = "tv"


class Sound(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sound: NoiseSound
    db: int = Decibels


class AutoNoise(BaseModel):
    """Sounds that start and stop at random: one under the whole call and a few that come and
    go. The seed fixes which ones and when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    db: int = Decibels
    seed: int = Field(default=1, ge=1)


class Speaker(BaseModel):
    """A person who talks behind the caller, in the caller's language, from start_s on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SpeakerKind
    db: int = Decibels
    start_s: float = Field(default=5, ge=0, le=600)


class Surroundings(BaseModel):
    """What the agent hears behind the caller. No sounds and no auto noise is a quiet room."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sounds: tuple[Sound, ...] = Field(default=(), max_length=len(NoiseSound))
    auto: AutoNoise | None = None
    speaker: Speaker | None = None

    @field_validator("sounds")
    @classmethod
    def in_one_order(cls, sounds: tuple[Sound, ...]) -> tuple[Sound, ...]:
        """The same sounds in another order are the same surroundings."""
        return tuple(sorted(sounds, key=lambda sound: list(NoiseSound).index(sound.sound)))

    @model_validator(mode="after")
    def one_kind_of_noise(self) -> Self:
        if self.sounds and self.auto is not None:
            raise ValueError("choose sounds or auto noise, not both")
        if len({sound.sound for sound in self.sounds}) != len(self.sounds):
            raise ValueError("each sound can be in the list once")
        return self


class Layer(BaseModel):
    """One sound file in a call: from start_s to end_s of the call, at a gain, looped or once.
    A layer with no end plays until the call ends."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str
    """The sound's path under the sounds folder, as `cafe.wav` or `speakers/en_tv_1.wav`; in a
    call request, the full path."""
    sound: NoiseSound | None = None
    """What plays: a noise, or a second speaker's clip (`speaker`)."""
    speaker: SpeakerKind | None = None
    gain: float = Field(gt=0)
    start_s: float = Field(ge=0)
    end_s: float | None = None
    loop: bool

    @model_validator(mode="after")
    def a_noise_or_a_speaker(self) -> Self:
        if (self.sound is None) == (self.speaker is None):
            raise ValueError("a layer is a noise sound or a speaker clip")
        return self


class SoundPlan(BaseModel):
    """Every sound a call plays behind the caller, decided before the call starts. A retry
    plays the same plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    layers: list[Layer] = []
