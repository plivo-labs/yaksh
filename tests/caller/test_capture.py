import io
import wave

from yaksha.caller.audio import (
    SAMPLE_RATE,
    CallerReply,
    CallRecording,
    Playout,
    caller_voice,
    placed,
)
from yaksha.domain.latency import AgentMedia, CallerReplyWindow, Span


def silence(seconds: float) -> bytes:
    return bytes(2 * round(SAMPLE_RATE * seconds))


def test_gaps_are_where_no_frames_came_and_the_track_holds_silence() -> None:
    frame = bytes(320)
    frames = [(1000, frame), (1020, frame), (1300, frame), (1320, frame)]

    audio, gaps = placed(frames, 1000)

    assert gaps == [Span(start_ms=40, end_ms=300)]
    assert len(audio) == 2 * SAMPLE_RATE * 340 // 1000


def test_the_agent_media_covers_the_line_and_names_its_gaps() -> None:
    recording = CallRecording()
    frame = bytes(320)
    for at_ms in (1300, 1320, 1600, 1620):
        recording.agent(frame, at_ms, None)

    media = recording.agent_media(1000)

    assert media == AgentMedia(first_ms=1300, last_ms=1640, gaps=[Span(start_ms=1340, end_ms=1600)])
    assert CallRecording().agent_media(1000) is None


def test_the_caller_voice_keeps_each_reply_as_it_went_out() -> None:
    def said(seconds: float) -> Playout:
        playout = Playout()
        playout.received(silence(seconds), now_ns=0)
        return playout

    replies = [
        CallerReply(start_ms=1000, end_ms=1600, playout=said(0.5), finished=True),
        CallerReply(start_ms=3000, end_ms=3200, playout=said(1.0)),
        CallerReply(start_ms=5000, playout=said(0.3)),
    ]

    voice_wav, windows = caller_voice(replies)

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
    assert voice_wav is not None
    with wave.open(io.BytesIO(voice_wav)) as voice:
        assert (voice.getnchannels(), voice.getnframes()) == (1, SAMPLE_RATE)
