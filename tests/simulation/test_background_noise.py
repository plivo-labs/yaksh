import math
import wave
from collections.abc import Sequence
from itertools import pairwise

import audioop
import pytest

from truman.caller.audio import FRAME_BYTES, SAMPLE_RATE
from truman.domain.background_noise import NoiseSound
from truman.simulation.background_noise import sound_path

SOUNDS = [sound for sound in NoiseSound if sound is not NoiseSound.NONE]
SPAN = SAMPLE_RATE  # half a second of 16-bit samples, in bytes
POINT_BYTES = 800  # 50 ms


def dbfs(fragment: bytes) -> float:
    return 20 * math.log10(max(audioop.rms(fragment, 2), 1) / 32768)


def level_change(before: bytes, after: bytes) -> float:
    return abs(dbfs(before) - dbfs(after))


def percentile_99(values: Sequence[float]) -> float:
    return sorted(values)[int(0.99 * (len(values) - 1))]


@pytest.mark.parametrize("sound", SOUNDS)
def test_every_sound_loops_cleanly_in_the_call_format(sound: NoiseSound) -> None:
    with wave.open(str(sound_path(sound))) as file:
        format_ = (file.getnchannels(), file.getsampwidth(), file.getframerate())
        audio = file.readframes(file.getnframes())
    samples = memoryview(audio).cast("h")
    steps = [abs(b - a) for a, b in pairwise(samples)]
    changes = [
        level_change(audio[at - SPAN : at], audio[at : at + SPAN])
        for at in range(SPAN, len(audio) - SPAN + 1, POINT_BYTES)
    ]

    assert format_ == (1, 2, SAMPLE_RATE)
    assert len(audio) % FRAME_BYTES == 0
    assert -25.5 <= dbfs(audio) <= -24.5
    assert audioop.max(audio, 2) <= 32768 * 10 ** (-3 / 20)
    assert abs(samples[0] - samples[-1]) <= percentile_99(steps)
    assert level_change(audio[-SPAN:], audio[:SPAN]) <= percentile_99(changes)
