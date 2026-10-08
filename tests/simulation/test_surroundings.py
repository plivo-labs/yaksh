import math
import wave
from collections.abc import Sequence
from itertools import pairwise

import audioop
import pytest

from yaksha.caller.audio import FRAME_BYTES, SAMPLE_RATE
from yaksha.domain.languages import Language
from yaksha.domain.surroundings import (
    AutoNoise,
    NoiseSound,
    Sound,
    Speaker,
    SpeakerKind,
    Surroundings,
)
from yaksha.simulation.surroundings import (
    SOUNDS,
    SPEAKER_GAP_S,
    clips_of,
    noise_file,
    sound_plan,
    speaker_clips,
)

SPAN = SAMPLE_RATE  # half a second of 16-bit samples, in bytes
POINT_BYTES = 800  # 50 ms


def dbfs(fragment: bytes) -> float:
    return 20 * math.log10(max(audioop.rms(fragment, 2), 1) / 32768)


def level_change(before: bytes, after: bytes) -> float:
    return abs(dbfs(before) - dbfs(after))


def percentile_99(values: Sequence[float]) -> float:
    return sorted(values)[int(0.99 * (len(values) - 1))]


def read(file: str) -> tuple[tuple[int, int, int], bytes]:
    with wave.open(str(SOUNDS / file)) as wav:
        return (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), wav.readframes(
            wav.getnframes()
        )


def speech_dbfs(audio: bytes) -> float:
    """The level of the 20 ms chunks within 30 dB of the loudest: the speech, not the pauses."""
    chunks = [audio[at : at + FRAME_BYTES] for at in range(0, len(audio), FRAME_BYTES)]
    loudest = max(audioop.rms(chunk, 2) for chunk in chunks)
    active = [chunk for chunk in chunks if audioop.rms(chunk, 2) > loudest / 31.6]
    return dbfs(b"".join(active))


@pytest.mark.parametrize("sound", list(NoiseSound))
def test_every_noise_loops_cleanly_in_the_call_format(sound: NoiseSound) -> None:
    format_, audio = read(noise_file(sound))
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


@pytest.mark.parametrize("clip", speaker_clips(), ids=lambda clip: clip.id)
def test_every_speaker_clip_talks_at_the_callers_level_in_the_call_format(clip) -> None:
    format_, audio = read(clip.file)

    assert format_ == (1, 2, SAMPLE_RATE)
    assert len(audio) % FRAME_BYTES == 0
    assert -20.5 <= speech_dbfs(audio) <= -19.5
    assert audioop.max(audio, 2) <= 32768 * 10 ** (-3 / 20) + 1
    assert abs(len(audio) / 2 / SAMPLE_RATE - clip.seconds) < 0.05
    assert [line.start_s for line in clip.lines] == sorted(line.start_s for line in clip.lines)
    assert all("[" not in line.text for line in clip.lines)


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize("kind", list(SpeakerKind))
def test_every_language_has_clips_of_every_speaker_kind(
    language: Language, kind: SpeakerKind
) -> None:
    assert clips_of(kind, language)


def test_sounds_play_through_the_whole_call_at_their_level() -> None:
    plan = sound_plan(
        Surroundings(
            sounds=(Sound(sound=NoiseSound.CAFE, db=0), Sound(sound=NoiseSound.CAR, db=-20))
        ),
        Language.EN,
        key="a",
        duration_s=60,
    )

    cafe, car = plan.layers
    assert (cafe.file, cafe.start_s, cafe.end_s, cafe.loop) == ("cafe.wav", 0, None, True)
    # 0 dB puts the -25 dBFS loop at the caller's -20 dBFS speech level; 20 dB less is a tenth.
    assert cafe.gain == pytest.approx(10 ** (5 / 20))
    assert car.gain == pytest.approx(cafe.gain / 10)


def test_a_speaker_talks_from_its_start_in_turns_with_pauses_until_the_call_ends() -> None:
    speaker = Speaker(kind=SpeakerKind.TALKS_TO_CALLER, db=-6, start_s=5)
    plan = sound_plan(Surroundings(speaker=speaker), Language.HI, key="a", duration_s=300)

    layers = plan.layers
    ends = [layer.end_s for layer in layers if layer.end_s is not None]
    gaps = [later.start_s - end for end, later in zip(ends, layers[1:], strict=False)]
    low, high = SPEAKER_GAP_S[SpeakerKind.TALKS_TO_CALLER]
    assert len(ends) == len(layers)
    assert layers[0].start_s == 5 and layers[-1].start_s < 300 <= ends[-1] + high
    assert all(layer.file.startswith("speakers/hi_talks_to_caller_") for layer in layers)
    assert all(not layer.loop for layer in layers)
    assert all(low - 0.01 <= gap <= high + 0.01 for gap in gaps)
    assert layers[0].gain == pytest.approx(10 ** (-6 / 20))


def test_auto_noise_keeps_one_sound_under_the_call_and_brings_others_in_and_out() -> None:
    auto = Surroundings(auto=AutoNoise(db=-10, seed=3))
    plan = sound_plan(auto, Language.EN, key="a", duration_s=300)

    under, *others = plan.layers
    assert (under.start_s, under.end_s) == (0, None)
    assert len(others) >= 5
    assert all(o.end_s is not None and 3 <= o.end_s - o.start_s <= 8.01 for o in others)
    assert all(o.file != under.file for o in others)
    assert all(o.start_s < 300 for o in others)


def test_the_same_key_plays_the_same_sounds_and_another_key_or_seed_others() -> None:
    surroundings = Surroundings(
        auto=AutoNoise(db=-10, seed=1),
        speaker=Speaker(kind=SpeakerKind.OWN_PHONE_CALL, db=0, start_s=0),
    )
    other_seed = surroundings.model_copy(update={"auto": AutoNoise(db=-10, seed=2)})

    def plan(of: Surroundings, key: str):
        return sound_plan(of, Language.EN, key=key, duration_s=300)

    assert plan(surroundings, "version/1") == plan(surroundings, "version/1")
    assert plan(surroundings, "version/1") != plan(surroundings, "version/2")
    assert plan(surroundings, "version/1") != plan(other_seed, "version/1")


def test_a_quiet_room_plays_nothing() -> None:
    assert sound_plan(Surroundings(), Language.EN, key="a", duration_s=60).layers == []


def test_sounds_and_auto_noise_do_not_go_together() -> None:
    with pytest.raises(ValueError, match="sounds or auto noise"):
        Surroundings(sounds=(Sound(sound=NoiseSound.CAFE, db=0),), auto=AutoNoise(db=0))


def test_the_same_sounds_in_another_order_are_the_same_surroundings() -> None:
    cafe, car = Sound(sound=NoiseSound.CAFE, db=-10), Sound(sound=NoiseSound.CAR, db=-20)

    assert Surroundings(sounds=(car, cafe)) == Surroundings(sounds=(cafe, car))
