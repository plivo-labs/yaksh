from pipecat.audio.vad.vad_analyzer import VADState

from yaksha.domain.latency import CallerReplyWindow, Span, Speech
from yaksha.evaluation.speech import Window, measure, placed_reply, segments

QUIET, STARTING, SPEAKING, STOPPING = (
    VADState.QUIET,
    VADState.STARTING,
    VADState.SPEAKING,
    VADState.STOPPING,
)
RATE = 8000


def silence(seconds: float) -> bytes:
    return bytes(2 * round(RATE * seconds))


def run(*states: VADState, window_ms: float = 32.0) -> list[Window]:
    return [((i + 1) * window_ms, window_ms, state) for i, state in enumerate(states)]


def test_speech_runs_from_the_decided_start_to_its_last_speaking_window() -> None:
    windows = run(QUIET, STARTING, STARTING, SPEAKING, SPEAKING, STOPPING, STOPPING, QUIET)

    assert segments(windows, 256) == [Span(start_ms=32, end_ms=160)]


def test_a_pause_shorter_than_the_stop_time_keeps_one_stretch_of_speech() -> None:
    windows = run(
        QUIET, QUIET, QUIET, STARTING, SPEAKING, STOPPING, STOPPING, SPEAKING, SPEAKING, QUIET
    )

    assert segments(windows, 320) == [Span(start_ms=64, end_ms=288)]


def test_speech_still_going_at_the_end_of_the_audio_ends_with_it() -> None:
    windows = run(QUIET, STARTING, SPEAKING, SPEAKING)

    assert segments(windows, 150) == [Span(start_ms=0, end_ms=150)]


def test_speech_that_was_stopping_at_the_end_ends_at_its_last_word() -> None:
    windows = run(QUIET, STARTING, SPEAKING, SPEAKING, STOPPING, STOPPING, STOPPING)

    assert segments(windows, 240) == [Span(start_ms=0, end_ms=128)]


def test_each_return_to_speaking_after_quiet_is_new_speech() -> None:
    windows = run(
        QUIET,
        QUIET,
        QUIET,
        STARTING,
        SPEAKING,
        STOPPING,
        QUIET,
        QUIET,
        STARTING,
        SPEAKING,
        SPEAKING,
    )

    assert segments(windows, 352) == [
        Span(start_ms=64, end_ms=160),
        Span(start_ms=224, end_ms=352),
    ]


def test_a_finished_reply_is_placed_back_from_where_its_audio_stopped() -> None:
    reply = CallerReplyWindow(
        start_ms=1000, end_ms=1600, finished=True, audio_start_ms=0, audio_ms=320
    )
    windows = run(QUIET, STARTING, SPEAKING, SPEAKING, SPEAKING, STOPPING, STOPPING, QUIET)

    assert placed_reply(reply, windows, 320, 9000) == ([Span(start_ms=1280, end_ms=1440)], 1440)


def test_a_cut_reply_runs_from_its_start_as_far_as_its_audio_went_out() -> None:
    reply = CallerReplyWindow(
        start_ms=3000, end_ms=3200, finished=False, audio_start_ms=0, audio_ms=320
    )
    windows = run(QUIET, QUIET, QUIET, SPEAKING, SPEAKING, SPEAKING, SPEAKING, SPEAKING)

    assert placed_reply(reply, windows, 320, 9000) == ([Span(start_ms=3032, end_ms=3200)], 3200)


def test_a_reply_the_call_cut_off_ends_with_the_call_and_has_no_speech_end() -> None:
    reply = CallerReplyWindow(
        start_ms=5000, end_ms=None, finished=False, audio_start_ms=0, audio_ms=320
    )
    windows = run(QUIET, QUIET, SPEAKING, SPEAKING, SPEAKING)

    assert placed_reply(reply, windows, 320, 5100) == ([Span(start_ms=5000, end_ms=5100)], None)


async def test_a_silent_call_has_no_speech_and_keeps_each_reply_end() -> None:
    replies = [
        CallerReplyWindow(start_ms=1000, end_ms=1500, finished=True, audio_start_ms=0, audio_ms=500)
    ]

    heard = await measure(silence(3), silence(0.5), RATE, 100, replies)

    assert heard.speech == Speech(agent=[], caller=[])
    assert (heard.replies, heard.end_ms) == ([(1000, 1500)], 3100)
