import wave
from pathlib import Path

from pipecat.audio.vad.vad_analyzer import VADState

from truman.caller.audio import (
    SAMPLE_RATE,
    CallerReply,
    CallRecording,
    Playout,
    placed,
    save_caller_voice,
)
from truman.caller.latency import Detector, Window, reply_speech, segments
from truman.domain.latency import AgentMedia, CallerReplyWindow, Latency, Span, Speech

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
    replies = [
        CallerReply(start_ms=1000, end_ms=1500, playout=playout, finished=True),
        CallerReply(2000),
    ]
    detector = Detector()
    try:
        measured = await detector.measure(silence(3), 100, 0, replies)
    finally:
        detector.start().shutdown()

    assert measured is not None
    assert measured.latency == Latency(replies=[], p50_ms=None, p90_ms=None)
    assert measured.speech == Speech(agent=[], caller=[])


def test_the_agent_media_covers_the_line_and_names_its_gaps() -> None:
    recording = CallRecording()
    frame = bytes(320)
    for at_ms in (1300, 1320, 1600, 1620):
        recording.agent(frame, at_ms, None)

    media = recording.agent_media(1000)

    assert media == AgentMedia(first_ms=1300, last_ms=1640, gaps=[Span(start_ms=1340, end_ms=1600)])
    assert CallRecording().agent_media(1000) is None


def test_the_caller_voice_keeps_each_reply_as_it_went_out(tmp_path: Path) -> None:
    def said(seconds: float) -> Playout:
        playout = Playout()
        playout.received(silence(seconds), now_ns=0)
        return playout

    replies = [
        CallerReply(start_ms=1000, end_ms=1600, playout=said(0.5), finished=True),
        CallerReply(start_ms=3000, end_ms=3200, playout=said(1.0)),
        CallerReply(start_ms=5000, playout=said(0.3)),
    ]
    path = tmp_path / "caller-voice.wav"

    windows = save_caller_voice(replies, path)

    assert windows == [
        CallerReplyWindow(
            start_ms=1000, end_ms=1600, finished=True, audio_start_ms=0, audio_ms=500
        ),
        CallerReplyWindow(
            start_ms=3000, end_ms=3200, finished=False, audio_start_ms=500, audio_ms=200
        ),
        CallerReplyWindow(
            start_ms=5000, end_ms=None, finished=False, audio_start_ms=700, audio_ms=300
        ),
    ]
    with wave.open(str(path)) as voice:
        assert (voice.getnchannels(), voice.getnframes()) == (1, SAMPLE_RATE * 1000 // 1000)
