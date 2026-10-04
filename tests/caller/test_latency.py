from pipecat.audio.vad.vad_analyzer import VADState

from truman.caller.audio import SAMPLE_RATE, Playout, placed
from truman.caller.latency import CallerReply, Detector, Window, reply_speech, segments
from truman.domain.latency import Latency, Span, Speech

QUIET, STARTING, SPEAKING, STOPPING = (
    VADState.QUIET,
    VADState.STARTING,
    VADState.SPEAKING,
    VADState.STOPPING,
)


def silence(seconds: float) -> bytes:
    return bytes(2 * round(SAMPLE_RATE * seconds))


def run(*states: VADState, window_ms: float = 32.0) -> list[Window]:
    return [((i + 1) * window_ms, window_ms, state) for i, state in enumerate(states)]


def test_speech_runs_from_the_decided_start_to_its_last_speaking_window() -> None:
    windows = run(QUIET, STARTING, STARTING, SPEAKING, SPEAKING, STOPPING, STOPPING, QUIET)

    assert segments(windows) == [Span(start_ms=32, end_ms=160)]


def test_a_pause_shorter_than_the_stop_time_keeps_one_stretch_of_speech() -> None:
    windows = run(
        QUIET, QUIET, QUIET, STARTING, SPEAKING, STOPPING, STOPPING, SPEAKING, SPEAKING, QUIET
    )

    assert segments(windows) == [Span(start_ms=64, end_ms=288)]


def test_speech_that_trails_off_at_the_end_of_the_audio_ends_at_its_last_word() -> None:
    windows = run(QUIET, STARTING, SPEAKING, SPEAKING, STOPPING, STOPPING, STOPPING)

    assert segments(windows) == [Span(start_ms=0, end_ms=128)]


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

    assert segments(windows) == [Span(start_ms=64, end_ms=160), Span(start_ms=224, end_ms=352)]


async def test_a_reply_cut_off_counts_from_its_first_audio_to_its_last() -> None:
    assert await reply_speech((1000, 2400, None)) == [Span(start_ms=1000, end_ms=2400)]
    assert await reply_speech((1000, None, None)) == []


def test_gaps_are_where_no_frames_came_and_the_track_holds_silence() -> None:
    frame = bytes(320)
    frames = [(1000, frame), (1020, frame), (1300, frame), (1320, frame)]

    audio, gaps = placed(frames, 1000)

    assert gaps == [Span(start_ms=40, end_ms=300)]
    assert len(audio) == 2 * SAMPLE_RATE * 340 // 1000


async def test_a_call_with_no_speech_is_measured_in_the_detector_process() -> None:
    playout = Playout()
    playout.received(silence(0.5), now_ns=0)
    replies = [CallerReply(start_ms=1000, end_ms=1500, playout=playout), CallerReply(2000)]
    gaps = [Span(start_ms=400, end_ms=900)]
    detector = Detector()
    try:
        measured = await detector.measure(silence(3), gaps, 100, 0, replies)
    finally:
        detector.start().shutdown()

    assert measured is not None
    assert measured.latency == Latency(replies=[], p50_ms=None, p90_ms=None)
    assert measured.speech == Speech(
        agent=[], caller=[], agent_gaps=[Span(start_ms=500, end_ms=1000)]
    )
