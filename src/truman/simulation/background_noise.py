"""The sound files that play behind the caller."""

from pathlib import Path

from truman.domain.background_noise import NoiseSound

SOUNDS = Path(__file__).parent / "sounds"
"""Read as files: the mixer opens a sound by its path."""


def sound_path(sound: NoiseSound) -> Path:
    return SOUNDS / f"{sound}.wav"
