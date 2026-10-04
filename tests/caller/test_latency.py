from truman.caller.audio import SAMPLE_RATE, Playout
from truman.caller.latency import CallerReply, Detector
from truman.domain.latency import Latency


def silence(seconds: float) -> bytes:
    return bytes(2 * round(SAMPLE_RATE * seconds))


async def test_a_call_with_no_speech_is_measured_in_the_detector_process() -> None:
    playout = Playout()
    playout.received(silence(0.5), now_ns=0)
    replies = [CallerReply(start_ms=1000, end_ms=1500, playout=playout), CallerReply(2000)]
    detector = Detector()
    try:
        measured = await detector.measure(silence(3), 0, 0, replies)
    finally:
        detector.start().shutdown()

    assert measured == Latency(replies=[], p50_ms=None, p90_ms=None)
