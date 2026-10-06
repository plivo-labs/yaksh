import io
import math
import wave
from array import array
from collections.abc import Sequence
from itertools import pairwise

import audioop
import pytest
from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer

from yaksha.caller.audio import FRAME_BYTES, SAMPLE_RATE
from yaksha.domain.background_noise import BackgroundNoise, NoiseLevel, NoiseSound
from yaksha.simulation.background_noise import (
    LEAD_S,
    TAIL_S,
    sound_path,
    volume,
    wav,
    with_noise,
)

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


@pytest.mark.parametrize("level", list(NoiseLevel))
async def test_a_preview_mixes_the_noise_as_a_call_does(level: NoiseLevel) -> None:
    # Two seconds at full scale: the sum clips, and a volume below 1 also cuts toward zero.
    voice = array("h", [32767, -32768] * SAMPLE_RATE)
    mixer = SoundfileMixer(
        sound_files={"cafe": str(sound_path(NoiseSound.CAFE))},
        default_sound="cafe",
        volume=volume(level),
    )
    await mixer.start(SAMPLE_RATE)
    padded = (
        bytes(int(2 * LEAD_S * SAMPLE_RATE))
        + voice.tobytes()
        + bytes(int(2 * TAIL_S * SAMPLE_RATE))
    )
    sent = [
        await mixer.mix(padded[at : at + FRAME_BYTES]) for at in range(0, len(padded), FRAME_BYTES)
    ]

    previewed = with_noise(wav(voice), BackgroundNoise(sound=NoiseSound.CAFE, level=level))

    with wave.open(io.BytesIO(previewed)) as file:
        assert file.readframes(file.getnframes()) == b"".join(sent)
