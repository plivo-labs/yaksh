import math
import wave
from itertools import pairwise

import audioop
import pytest

from yaksh.caller.audio import FRAME_BYTES, SAMPLE_RATE
from yaksh.domain.answering import (
    AfterScreening,
    AnsweredBy,
    Answering,
    MachineLine,
    Screener,
    Voicemail,
)
from yaksh.simulation.answering import (
    SCREENERS,
    SOUNDS,
    TONE,
    VOICEMAILS,
    answering_plan,
    line_file,
    line_texts,
)


def read(file: str) -> tuple[tuple[int, int, int], bytes]:
    with wave.open(str(SOUNDS / file)) as sound:
        return (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()), sound.readframes(
            sound.getnframes()
        )


def dbfs(fragment: bytes) -> float:
    return 20 * math.log10(max(audioop.rms(fragment, 2), 1) / 32768)


def peak_dbfs(audio: bytes) -> float:
    return 20 * math.log10(max(abs(s) for s in memoryview(audio).cast("h")) / 32768)


def speech_dbfs(audio: bytes) -> float:
    chunks = [audio[at : at + FRAME_BYTES] for at in range(0, len(audio), FRAME_BYTES)]
    loudest = max(audioop.rms(chunk, 2) for chunk in chunks)
    return dbfs(b"".join(chunk for chunk in chunks if audioop.rms(chunk, 2) > loudest / 31.6))


@pytest.mark.parametrize("line_id", list(line_texts()))
def test_every_line_is_speech_at_the_callers_level_in_the_call_format(line_id: str) -> None:
    form, audio = read(line_file(line_id))

    assert form == (1, 2, SAMPLE_RATE)
    assert len(audio) % FRAME_BYTES == 0
    assert speech_dbfs(audio) == pytest.approx(-20, abs=1)
    assert peak_dbfs(audio) <= -3 + 0.1


def test_the_tone_is_one_second_of_440_hz_with_a_6_dbfs_peak() -> None:
    form, audio = read(TONE)
    samples = memoryview(audio).cast("h")
    crossings = sum(1 for a, b in pairwise(samples) if a < 0 <= b)

    assert form == (1, 2, SAMPLE_RATE)
    assert len(samples) == SAMPLE_RATE
    assert crossings == pytest.approx(440, abs=2)
    assert peak_dbfs(audio) == pytest.approx(-6, abs=0.1)


def test_every_preset_plays_lines_that_are_listed() -> None:
    used = {preset.greeting for preset in VOICEMAILS.values()} | {
        line_id
        for preset in SCREENERS.values()
        for line_id in (preset.prompt, *preset.follow_ups, preset.acknowledgement, preset.reply)
    }

    assert set(VOICEMAILS) == set(Voicemail)
    assert set(SCREENERS) == set(Screener)
    assert used <= set(line_texts())


def test_the_persona_answers_with_no_plan() -> None:
    assert answering_plan(AnsweredBy.CALLER, Answering()) is None


def test_a_voicemail_plays_its_standard_greeting_and_the_tone() -> None:
    plan = answering_plan(AnsweredBy.VOICEMAIL, Answering(voicemail=Voicemail.CARRIER))

    assert plan is not None and plan.screener is None and plan.voicemail is not None
    assert plan.voicemail.greeting is not None
    assert plan.voicemail.greeting.line is MachineLine.GREETING
    assert plan.voicemail.greeting.text == line_texts()["carrier_greeting"]
    assert plan.voicemail.own_greeting is None
    assert plan.voicemail.tone is not None and plan.voicemail.tone.endswith("tone.wav")


def test_a_persona_with_its_own_greeting_says_it_in_place_of_the_standard_one() -> None:
    answering = Answering(voicemail=Voicemail.CARRIER_NO_TONE, greeting="Hi, it's Rachel.")
    plan = answering_plan(AnsweredBy.VOICEMAIL, answering)

    assert plan is not None and plan.voicemail is not None
    assert (plan.voicemail.greeting, plan.voicemail.own_greeting) == (None, "Hi, it's Rachel.")
    assert plan.voicemail.tone is None


def test_a_full_mailbox_plays_its_line_and_no_greeting_of_the_persona() -> None:
    answering = Answering(voicemail=Voicemail.MAILBOX_FULL, greeting="Hi, it's Rachel.")
    plan = answering_plan(AnsweredBy.VOICEMAIL, answering)

    assert plan is not None and plan.voicemail is not None and plan.voicemail.full
    assert plan.voicemail.greeting is not None
    assert plan.voicemail.greeting.line is MachineLine.MAILBOX_FULL
    assert plan.voicemail.own_greeting is None


@pytest.mark.parametrize("after", list(AfterScreening))
def test_a_screener_hands_on_to_the_voicemail_only_when_the_persona_sends_it_there(
    after: AfterScreening,
) -> None:
    answering = Answering(screener=Screener.PIXEL_CALL_ASSIST, after_screening=after)
    plan = answering_plan(AnsweredBy.SCREENER, answering)

    assert plan is not None and plan.screener is not None
    assert plan.screener.after is after
    assert [clip.text for clip in plan.screener.follow_ups] == [
        line_texts()["pixel_assist_follow_up"]
    ]
    assert plan.screener.reply.line is MachineLine.REPLY
    assert (plan.voicemail is not None) is (after is AfterScreening.VOICEMAIL)
