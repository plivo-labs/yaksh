import base64
import io
import json
import wave

import audioop
from pipecat.frames.frames import (
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputDTMFUrgentFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.tests.utils import run_test

from tests.conftest import FixedClock, Observer
from yaksh.caller.audio import FRAME_BYTES, GAP_BYTES, PLAYOUT, SAMPLE_RATE, CallRecording, Clock
from yaksh.caller.phone import CHUNK_BYTES, Checkpoints, KeyPresses, StreamSerializer
from yaksh.caller.transcript import TranscriptBuilder
from yaksh.domain.conversations import Provenance, WireEventKind

STREAM = "stream-1"
LOUD = b"\x00\x10" * (FRAME_BYTES // 2)
QUIET = b"\x00" * FRAME_BYTES
HUSH = b"\x01\x00" * (FRAME_BYTES // 2)
LINEAR = "audio/x-l16;rate=8000"
PLIVO_EPOCH = 1_705_312_199_000
"""Plivo's clock when Yaksh's clock reads 0."""


def media(pcm: bytes, timestamp: int | None = None) -> str:
    body = {"payload": base64.b64encode(pcm).decode()}
    if timestamp is not None:
        body["timestamp"] = str(timestamp)
    return json.dumps({"event": "media", "media": body})


def silence(ms: int) -> bytes:
    return bytes(ms * SAMPLE_RATE // 1000 * 2)


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
        TTSTextFrame("Hello", text_type="word"),
        TTSTextFrame("there", text_type="word"),
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
            word.text, word.metadata["yaksh.offset"], word.metadata[PLAYOUT], self_spaced=False
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
    serializer = StreamSerializer(
        STREAM, "audio/x-mulaw", Clock(), observer, checkpoints, CallRecording()
    )
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
    serializer = StreamSerializer(STREAM, LINEAR, Clock(), observer, checkpoints, CallRecording())

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
    hiccup = json.dumps({"event": "playFailed", "reason": "codec mismatch"})
    assert await serializer.deserialize(hiccup) is None
    assert not serializer.failed.is_set()
    assert serializer.failure == "plivo could not play audio: codec mismatch"
    assert await serializer.deserialize(json.dumps({"event": "stop"})) is None
    assert await serializer.deserialize("not json") is None
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
        WireEventKind.CALLER_ERROR,
        WireEventKind.STOP,
        WireEventKind.CALLER_ERROR,
    ]
    assert serializer.stopped.is_set() and serializer.failed.is_set()
    assert serializer.failure == (
        "plivo reported an error: stream torn down; "
        "before it, plivo could not play audio: codec mismatch"
    )


async def test_audio_that_plivo_cannot_play_after_the_stream_stopped_is_not_a_failure() -> None:
    observer = Observer()
    transcript = TranscriptBuilder(Clock(), observer)
    checkpoints = Checkpoints(STREAM, transcript)
    serializer = StreamSerializer(STREAM, LINEAR, Clock(), observer, checkpoints, CallRecording())

    await serializer.deserialize(json.dumps({"event": "stop"}))
    await serializer.deserialize(json.dumps({"event": "playFailed", "reason": "stream closed"}))

    assert serializer.failure is None
    assert observer.kinds() == [WireEventKind.STOP]


async def test_a_recording_puts_each_side_where_it_was_on_the_line() -> None:
    clock = FixedClock()
    recording = CallRecording()
    serializer = StreamSerializer(
        STREAM,
        LINEAR,
        clock,
        Observer(),
        Checkpoints(STREAM, TranscriptBuilder(clock, Observer())),
        recording,
    )
    connected = 1_000
    for line in range(960, 5_000, 20):
        # The agent greets from before connected, while its frames wait in the socket for the
        # pipeline to start at 2_400, and a stall holds the frames from 3_000 to 3_600. The
        # recording starts at the agent's first frame, two frames before connected.
        clock.now = max(line, 2_400) if line < 3_000 else max(line, 3_600)
        speech = line < connected or 1_200 <= line < 2_000 or 3_100 <= line < 3_300
        await serializer.deserialize(media(LOUD if speech else HUSH, PLIVO_EPOCH + line))
    jitter = [0, 6, -3, 4, -5] * 4
    sends = [2_400 + 20 * n + jitter[n] for n in range(20)] + [4_000 + 20 * n for n in range(10)]
    for sent in sends:
        clock.now = sent
        await serializer.serialize(OutputAudioRawFrame(LOUD, SAMPLE_RATE, 1))

    start = recording.start_ms(connected)
    saved = recording.to_wav(start)

    assert start == 960
    assert saved is not None
    with wave.open(io.BytesIO(saved)) as file:
        assert (file.getnchannels(), file.getframerate()) == (2, SAMPLE_RATE)
        audio = file.readframes(file.getnframes())
    assert audioop.tomono(audio, 2, 1, 0) == (
        LOUD * 2 + HUSH * 10 + LOUD * 40 + HUSH * 55 + LOUD * 10 + HUSH * 85
    )
    assert audioop.tomono(audio, 2, 0, 1) == (
        silence(1_440) + LOUD * 20 + silence(1_200) + LOUD * 10 + silence(800)
    )


def test_a_recording_starts_at_connected_when_no_agent_audio_came_before() -> None:
    recording = CallRecording()
    recording.agent(LOUD, 1_300, PLIVO_EPOCH + 1_200)
    recording.agent(LOUD, 1_320, PLIVO_EPOCH + 1_220)

    assert recording.start_ms(1_000) == 1_000


async def test_a_key_press_goes_to_plivo_as_one_send_dtmf_message() -> None:
    [sent], _ = await run_test(
        KeyPresses(), frames_to_send=[OutputDTMFUrgentFrame.from_string("4111#")]
    )

    assert isinstance(sent, OutputTransportMessageUrgentFrame)
    assert sent.message == {"event": "sendDTMF", "dtmf": "4111#"}
