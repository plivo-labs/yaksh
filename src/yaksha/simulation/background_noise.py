"""The sound files that play behind the caller, and the preview mix of a voice with one."""

import io
import wave
from array import array
from pathlib import Path

from yaksha.domain.background_noise import BackgroundNoise, NoiseLevel, NoiseMix, NoiseSound

SOUNDS = Path(__file__).parent / "sounds"
"""Read as files: the mixer opens a sound by its path."""
SAMPLE_RATE = 8000
SPEECH_DBFS = -20.0
"""The active speech level of the built-in voices at their persona settings on a call
(eleven_flash_v2_5, pcm_8000), measured at -20.5 to -19.2 dBFS on 2026-10-01."""
NOISE_DBFS = -25.0
"""The RMS level of every sound file."""
LEAD_S = 1.0
"""Noise before the voice in a preview, as a call has noise before the caller speaks."""
TAIL_S = 0.5


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


def with_noise(voice_wav: bytes, noise: BackgroundNoise | None) -> bytes:
    """The voice with the noise under it, LEAD_S of noise before it and TAIL_S after it. The
    sum is the one SoundfileMixer makes: each voice sample plus the noise sample times the
    volume, clipped to 16 bits and cut toward zero."""
    mix = None if noise is None else noise_mix(noise)
    if mix is None:
        return voice_wav
    loop = samples(mix.path.read_bytes(), mix.path.name)
    padded = silence(LEAD_S) + samples(voice_wav, "the voice") + silence(TAIL_S)
    mixed = array(
        "h",
        (
            int(min(32767.0, max(-32768.0, sample + loop[i % len(loop)] * mix.volume)))
            for i, sample in enumerate(padded)
        ),
    )
    return wav(mixed)


def check_format(file: wave.Wave_read, name: str) -> None:
    if (file.getnchannels(), file.getsampwidth(), file.getframerate()) != (1, 2, SAMPLE_RATE):
        raise ValueError(f"{name} is not 8 kHz 16-bit mono audio")


def samples(data: bytes, name: str) -> array[int]:
    with wave.open(io.BytesIO(data)) as file:
        check_format(file, name)
        return array("h", file.readframes(file.getnframes()))


def silence(seconds: float) -> array[int]:
    return array("h", bytes(2 * int(seconds * SAMPLE_RATE)))


def wav(audio: array[int]) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SAMPLE_RATE)
        file.writeframes(audio.tobytes())
    return out.getvalue()
