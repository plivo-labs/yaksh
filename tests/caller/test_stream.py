import base64
import json

import audioop
from pipecat.frames.frames import (
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.tests.utils import run_test

from tests.conftest import Observer
from truman.caller.audio import FRAME_BYTES, GAP_BYTES, PLAYOUT, SAMPLE_RATE, Clock
from truman.caller.phone import CHUNK_BYTES, Checkpoints, StreamSerializer
from truman.caller.transcript import TranscriptBuilder
from truman.domain.conversations import Provenance, WireEventKind

STREAM = "stream-1"
LOUD = b"\x00\x10" * (FRAME_BYTES // 2)
QUIET = b"\x00" * FRAME_BYTES


def media(pcm: bytes) -> str:
    return json.dumps({"event": "media", "media": {"payload": base64.b64encode(pcm).decode()}})


async def test_checkpoints_follow_the_audio_and_their_reports_close_the_reply() -> None:
    observer = Observer()
    transcript = TranscriptBuilder(Clock(), observer)
    checkpoints = Checkpoints(STREAM, transcript)
    transcript.generation_started()
    transcript.generated("Hello there")
    transcript.generation_ended()
    started = TTSStartedFrame()
    first, second = (
        TTSAudioRawFrame(LOUD * 5, SAMPLE_RATE, 1),
        TTSAudioRawFrame(LOUD * 3, SAMPLE_RATE, 1),
    )
    hello, there = (
        TTSTextFrame("Hello", aggregated_by="word"),
        TTSTextFrame("there", aggregated_by="word"),
    )

    downstream, _ = await run_test(
        checkpoints, frames_to_send=[started, first, hello, second, there, TTSStoppedFrame()]
    )
    names = [f.message["name"] for f in downstream if isinstance(f, OutputTransportMessageFrame)]
    audio = [len(f.audio) for f in downstream if isinstance(f, TTSAudioRawFrame)]
    playout = started.metadata[PLAYOUT]
    for word in (hello, there):
        transcript.caller_started(word.metadata[PLAYOUT])
        transcript.transmitted(
            word.text, word.metadata["truman.offset"], word.metadata[PLAYOUT], self_spaced=False
        )
    transcript.reply_ended(playout)
    assert observer.turns == []
    checkpoints.played(names[0])
    assert observer.turns == [] and not playout.caught_up(2)
    checkpoints.played(names[-1])

    assert names == [f"1:{FRAME_BYTES * 5}", f"1:{FRAME_BYTES * 8}"]
    assert audio == [FRAME_BYTES * 5, FRAME_BYTES * 3]
    assert [
        m.message["streamId"] for m in downstream if isinstance(m, OutputTransportMessageFrame)
    ] == [STREAM] * 2
    assert playout.arrived == FRAME_BYTES * 8 and playout.caught_up(2) and not playout.caught_up(1)
    assert [(t.provenance, t.text) for t in observer.turns] == [
        (Provenance.TRANSMITTED, "Hello there")
    ]


async def test_long_replies_get_a_checkpoint_every_500_ms() -> None:
    checkpoints = Checkpoints(STREAM, TranscriptBuilder(Clock(), Observer()))
    long = TTSAudioRawFrame(LOUD * 65, SAMPLE_RATE, 1)

    downstream, _ = await run_test(checkpoints, frames_to_send=[TTSStartedFrame(), long])

    audio = [len(f.audio) for f in downstream if isinstance(f, TTSAudioRawFrame)]
    names = [f.message["name"] for f in downstream if isinstance(f, OutputTransportMessageFrame)]
    assert audio == [CHUNK_BYTES, CHUNK_BYTES, FRAME_BYTES * 65 - 2 * CHUNK_BYTES]
    assert names == [f"1:{CHUNK_BYTES}", f"1:{2 * CHUNK_BYTES}", f"1:{FRAME_BYTES * 65}"]


async def test_a_mulaw_stream_is_decoded_and_answered_in_mulaw() -> None:
    observer = Observer()
    checkpoints = Checkpoints(STREAM, TranscriptBuilder(Clock(), observer))
    serializer = StreamSerializer(STREAM, "audio/x-mulaw", Clock(), observer, checkpoints)
    ulaw = audioop.lin2ulaw(LOUD, 2)

    heard = await serializer.deserialize(media(ulaw))
    play = json.loads(await serializer.serialize(OutputAudioRawFrame(LOUD, SAMPLE_RATE, 1)) or "")

    assert isinstance(heard, InputAudioRawFrame) and heard.audio == audioop.ulaw2lin(ulaw, 2)
    assert play["media"]["contentType"] == "audio/x-mulaw"
    assert base64.b64decode(play["media"]["payload"]) == ulaw
    assert observer.kinds() == [WireEventKind.AGENT_AUDIO]


async def test_the_serializer_speaks_linear_audio_and_reports_what_plivo_says() -> None:
    observer = Observer()
    transcript = TranscriptBuilder(Clock(), observer)
    checkpoints = Checkpoints(STREAM, transcript)
    serializer = StreamSerializer(STREAM, "audio/x-l16;rate=8000", Clock(), observer, checkpoints)

    play = json.loads(await serializer.serialize(OutputAudioRawFrame(LOUD, SAMPLE_RATE, 1)) or "")
    clear = json.loads(await serializer.serialize(InterruptionFrame()) or "")
    passthrough = await serializer.serialize(
        OutputTransportMessageFrame({"event": "checkpoint", "streamId": STREAM, "name": "1:320"})
    )
    heard = await serializer.deserialize(media(LOUD))
    for _ in range(GAP_BYTES // FRAME_BYTES + 1):
        await serializer.deserialize(media(QUIET))
    await serializer.deserialize(media(LOUD))
    await serializer.deserialize(media(LOUD))
    assert (
        await serializer.deserialize(json.dumps({"event": "playedStream", "name": "9:9"})) is None
    )
    assert await serializer.deserialize(json.dumps({"event": "stop"})) is None
    assert await serializer.deserialize("not json") is None
    hiccup = json.dumps({"event": "playFailed", "reason": "codec mismatch"})
    assert await serializer.deserialize(hiccup) is None
    assert not serializer.failed.is_set()
    failure = json.dumps({"event": "error", "reason": "stream torn down"})
    assert await serializer.deserialize(failure) is None

    assert play == {
        "event": "playAudio",
        "media": {
            "contentType": "audio/x-l16",
            "sampleRate": SAMPLE_RATE,
            "payload": base64.b64encode(LOUD).decode(),
        },
    }
    assert clear == {"event": "clearAudio", "streamId": STREAM}
    assert passthrough and json.loads(passthrough)["name"] == "1:320"
    assert isinstance(heard, InputAudioRawFrame)
    assert heard.audio == LOUD and heard.sample_rate == SAMPLE_RATE
    assert observer.kinds() == [
        WireEventKind.CLEAR_AUDIO,
        WireEventKind.AGENT_AUDIO,
        WireEventKind.AGENT_AUDIO,
        WireEventKind.STOP,
        WireEventKind.CALLER_ERROR,
        WireEventKind.CALLER_ERROR,
    ]
    assert serializer.stopped.is_set() and serializer.failed.is_set()
    assert serializer.failure == "plivo reported an error: stream torn down"
