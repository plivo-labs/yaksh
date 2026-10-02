"""The sound files that play behind the caller."""

import wave
from pathlib import Path

from truman.domain.background_noise import BackgroundNoise, NoiseLevel, NoiseMix, NoiseSound

SOUNDS = Path(__file__).parent / "sounds"
"""Read as files: the mixer opens a sound by its path."""
SAMPLE_RATE = 8000
SPEECH_DBFS = -20.0
"""The active speech level of the built-in voices at their persona settings on a call
(eleven_flash_v2_5, pcm_8000), measured at -20.5 to -19.2 dBFS on 2026-10-01."""
NOISE_DBFS = -25.0
"""The RMS level of every sound file."""


def sound_path(sound: NoiseSound) -> Path:
    return SOUNDS / f"{sound}.wav"


def volume(level: NoiseLevel) -> float:
    """The gain that puts the noise level.snr_db below the caller's speech."""
    return 10 ** ((SPEECH_DBFS - level.snr_db - NOISE_DBFS) / 20)


def noise_mix(noise: BackgroundNoise) -> NoiseMix | None:
    """None for no noise. A missing file, or one the mixer would skip, raises: the call then
    fails with a reason instead of running without the noise it names."""
    if noise.sound is NoiseSound.NONE:
        return None
    path = sound_path(noise.sound)
    with wave.open(str(path)) as file:
        check_format(file, path.name)
    return NoiseMix(path=path, volume=volume(noise.level))


def check_format(file: wave.Wave_read, name: str) -> None:
    if (file.getnchannels(), file.getsampwidth(), file.getframerate()) != (1, 2, SAMPLE_RATE):
        raise ValueError(f"{name} is not 8 kHz 16-bit mono audio")
