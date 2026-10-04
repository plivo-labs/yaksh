from pipecat.frames.frames import CancelFrame, InterruptionFrame, TTSStartedFrame, TTSTextFrame
from pipecat.tests.utils import run_test

from tests.conftest import FixedClock, Observer
from truman.caller.audio import FRAME_BYTES, Clock, Playout
from truman.caller.transcript import OFFSET, PLAYOUT, TranscriptBuilder, WireTap
from truman.domain.conversations import Provenance, Role


def played(arrived: int, sent: int) -> Playout:
    playout = Playout()
    playout.received(bytes(arrived), 0)
    playout.played(sent)
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


def test_the_line_is_quiet_only_once_the_last_words_are_reported_played() -> None:
    builder = TranscriptBuilder(Clock(), Observer())
    assert builder.quiet
    builder.scripted("Okay, thanks. Bye.")
    assert not builder.quiet
    playout = played(arrived=9_600, sent=0)
    builder.caller_started(playout)
    builder.transmitted("Okay,", 0, playout, self_spaced=False)
    builder.reply_ended()
    assert not builder.quiet

    playout.played(9_600)
    builder.audio_progressed()
    assert builder.quiet

    builder.agent_started()
    assert not builder.quiet


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
    playout.played(9_600 - FRAME_BYTES // 2)
    builder.audio_progressed()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "Yes please.")
    ]


def test_a_last_word_that_lands_after_the_end_frame_stays_in_its_turn() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes please.")
    playout = played(arrived=9_600, sent=9_600)
    playout.stamp_word(None)
    playout.stamp_word(None)
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


def test_a_reply_without_audio_is_unconfirmed_even_when_its_words_were_released() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes please.")
    playout = played(arrived=0, sent=0)
    builder.caller_started(playout)
    builder.transmitted("Yes", 0, playout, self_spaced=False)
    builder.transmitted("please.", 0, playout, self_spaced=False)

    builder.reply_ended()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.UNCONFIRMED, "Yes please.")
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


def test_an_agent_turn_runs_from_its_first_voice_to_its_last_minus_the_detector_delay() -> None:
    observer = Observer()
    clock = FixedClock()
    builder = TranscriptBuilder(clock, observer)
    clock.now = 1_000
    builder.agent_voice_started(0.1)
    builder.agent_started()
    clock.now = 3_000
    builder.agent_voice_stopped(0.6)
    clock.now = 3_400
    builder.agent_stopped()

    builder.agent_said("Hello, how can I help?")

    (turn,) = observer.turns
    assert turn.role is Role.AGENT and turn.text == "Hello, how can I help?"
    assert (turn.started_at_ms, turn.ended_at_ms) == (900, 2_400)


def test_self_spaced_pieces_cut_at_the_right_word() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Hello there friend")
    playout = played(arrived=24_000, sent=6_400)
    builder.caller_started(playout)
    for piece, start in (("Hel", 0), ("lo ", 3_200), ("there ", 6_400), ("friend", 12_800)):
        builder.transmitted(piece, start, playout, self_spaced=True)

    builder.caller_interrupted()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "Hello"),
        (Provenance.CUT, "there friend"),
    ]


def test_spoken_words_that_differ_from_the_text_leave_only_the_unheard_spoken_words() -> None:
    """Spoken words normally echo the text; when they do not, nothing is guessed."""
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "It costs $20 today.")
    playout = played(arrived=24_000, sent=9_600)
    builder.caller_started(playout)
    for word, start in (("It", 0), ("costs", 1_600), ("twenty", 4_800), ("dollars", 9_600)):
        builder.transmitted(word, start, playout, self_spaced=False)
    builder.transmitted("today.", 14_400, playout, self_spaced=False)

    builder.caller_interrupted()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.TRANSMITTED, "It costs twenty"),
        (Provenance.CUT, "dollars today."),
    ]


def test_a_scripted_nudge_is_marked_and_keeps_the_next_reply_matched_to_its_text() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    builder.scripted("Hello? Are you still there?")
    nudge = played(arrived=3_200, sent=3_200)
    builder.caller_started(nudge)
    builder.transmitted("Hello? Are you still there?", 0, nudge, self_spaced=False)
    builder.reply_ended(nudge)
    generated(builder, "I need to change my booking.")
    reply = played(arrived=24_000, sent=4_800)
    builder.caller_started(reply)
    for word, start in (("I", 0), ("need", 1_600), ("to", 4_800)):
        builder.transmitted(word, start, reply, self_spaced=False)

    builder.caller_interrupted()

    assert [(turn.text, turn.provenance, turn.scripted) for turn in observer.turns] == [
        ("Hello? Are you still there?", Provenance.TRANSMITTED, True),
        ("I need", Provenance.TRANSMITTED, False),
        ("to change my booking.", Provenance.CUT, False),
    ]


async def test_a_cancelled_pipeline_leaves_unplayed_words_unconfirmed_not_cut() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "Yes please.")
    playout = played(arrived=0, sent=0)
    started = TTSStartedFrame()
    started.metadata[PLAYOUT] = playout
    word = TTSTextFrame("Yes", aggregated_by="word")
    word.metadata[PLAYOUT] = playout
    word.metadata[OFFSET] = 0

    async def settled() -> None:
        pass

    await run_test(
        WireTap(builder, settled),
        frames_to_send=[started, word, CancelFrame()],
        expected_down_frames=None,
    )

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.UNCONFIRMED, "Yes please.")
    ]


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


def test_a_nudge_cut_before_its_audio_does_not_mark_the_next_reply_as_scripted() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    builder.scripted("Hello? Are you still there?")
    builder.caller_interrupted()
    generated(builder, "Sure, my name is Ravi.")
    playout = played(arrived=3_200, sent=3_200)
    builder.caller_started(playout)
    builder.transmitted("Sure, my name is Ravi.", 0, playout, self_spaced=False)

    builder.reply_ended(playout)

    assert [(turn.text, turn.provenance, turn.scripted) for turn in observer.turns] == [
        ("Hello? Are you still there?", Provenance.CUT, True),
        ("Sure, my name is Ravi.", Provenance.TRANSMITTED, False),
    ]


def test_noise_without_words_does_not_stretch_the_next_agent_turn() -> None:
    observer = Observer()
    clock = FixedClock()
    builder = TranscriptBuilder(clock, observer)
    clock.now = 1_000
    builder.agent_voice_started(0.1)
    builder.agent_started()
    clock.now = 1_500
    builder.agent_voice_stopped(0.2)
    builder.agent_stopped()
    clock.now = 60_000
    builder.agent_voice_started(0.1)
    builder.agent_started()
    clock.now = 62_000
    builder.agent_voice_stopped(0.6)
    builder.agent_stopped()

    builder.agent_said("Are you there?")

    (turn,) = observer.turns
    assert (turn.started_at_ms, turn.ended_at_ms) == (59_900, 61_400)


def test_text_generated_but_never_started_is_kept_as_unconfirmed_when_the_call_ends() -> None:
    observer = Observer()
    builder = TranscriptBuilder(Clock(), observer)
    generated(builder, "One more thing.")

    builder.call_ended()

    assert [(turn.provenance, turn.text) for turn in observer.turns] == [
        (Provenance.UNCONFIRMED, "One more thing.")
    ]
