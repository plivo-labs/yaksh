from pipecat.frames.frames import InterruptionFrame, TTSStartedFrame, TTSTextFrame
from pipecat.tests.utils import run_test

from tests.caller.test_plivo import Observer
from truman.caller.plivo import FRAME_BYTES, Clock, Playout
from truman.caller.transcript import OFFSET, PLAYOUT, TranscriptBuilder, WireTap
from truman.domain.conversations import Provenance, Role


def played(arrived: int, sent: int) -> Playout:
    playout = Playout()
    playout.arrived, playout.sent = arrived, sent
    return playout


def generated(builder: TranscriptBuilder, text: str) -> None:
    builder.generation_started()
    builder.generated(text)
    builder.generation_ended()


def test_an_interrupted_reply_keeps_what_the_agent_heard_apart_from_the_rest() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "I would like to book a table for two tonight.")
    playout = played(arrived=24_000, sent=8_000)
    builder.caller_started(playout)
    for word, start in (("I", 0), ("would", 1_600), ("like", 4_800), ("to", 8_000)):
        builder.transmitted(word, start, playout, self_spaced=False)

    builder.caller_interrupted()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "I would like"),
        (Provenance.CUT, "to book a table for two tonight."),
    ]


def test_a_finished_reply_is_recorded_once_the_wire_has_sent_it() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes please.")
    playout = played(arrived=9_600, sent=3_200)
    builder.caller_started(playout)
    builder.transmitted("Yes", 0, playout, self_spaced=False)
    builder.transmitted("please.", 6_400, playout, self_spaced=False)

    builder.reply_ended()
    assert observer.turns == []
    playout.sent = 9_600 - FRAME_BYTES // 2
    builder.audio_progressed()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "Yes please.")
    ]


def test_a_last_word_that_lands_after_the_end_frame_stays_in_its_turn() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes please.")
    playout = played(arrived=9_600, sent=9_600)
    playout.words = 2
    builder.caller_started(playout)
    builder.transmitted("Yes", 0, playout, self_spaced=False)

    builder.reply_ended(playout)
    assert observer.turns == []
    builder.transmitted("please.", 6_400, playout, self_spaced=False)

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "Yes please.")
    ]


def test_a_word_of_a_closed_reply_does_not_start_a_new_one() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes please.")
    playout = played(arrived=9_600, sent=9_600)
    builder.caller_started(playout)
    builder.transmitted("Yes", 0, playout, self_spaced=False)
    builder.reply_ended(playout)

    builder.transmitted("please.", 6_400, playout, self_spaced=False)
    builder.call_ended()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "Yes")
    ]


def test_a_reply_without_audio_is_all_cut_even_when_its_words_were_released() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes please.")
    playout = played(arrived=0, sent=0)
    builder.caller_started(playout)
    builder.transmitted("Yes", 0, playout, self_spaced=False)
    builder.transmitted("please.", 0, playout, self_spaced=False)

    builder.reply_ended()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.CUT, "Yes please.")
    ]


def test_a_reply_cut_before_any_audio_is_all_cut() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    builder.generation_started()
    builder.generated("Actually, never mind.")

    builder.caller_interrupted()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.CUT, "Actually, never mind.")
    ]


def test_an_agent_turn_is_timed_by_its_speech_and_worded_by_the_aggregator() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    builder.agent_stopped()
    builder.agent_started()

    builder.agent_said("Hello, how can I help?")

    (turn,) = observer.turns
    assert turn.role is Role.AGENT and turn.text == "Hello, how can I help?"
    assert turn.provenance is None and turn.started_at_ms <= turn.ended_at_ms


async def test_words_queued_before_an_interruption_are_counted_before_the_cut() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes.")
    playout = played(arrived=3_200, sent=3_200)
    started = TTSStartedFrame()
    started.metadata[PLAYOUT] = playout
    word = TTSTextFrame("Yes.", aggregated_by="word")
    word.metadata[PLAYOUT] = playout
    word.metadata[OFFSET] = 0

    async def settled() -> None:
        pass

    await run_test(WireTap(builder, settled), frames_to_send=[started, word, InterruptionFrame()])

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "Yes.")
    ]
