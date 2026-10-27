"""A phone conversation over the stream Plivo opens: the Pipecat pipeline, what it sends and
hears, and what it leaves when it ends. `Conversations` decide where a conversation runs."""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import audioop
from fastapi import WebSocket
from pipecat.frames.frames import (
    AudioRawFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputDTMFUrgentFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from yaksh.caller.answering import AnsweringScript
from yaksh.caller.audio import (
    GAP_BYTES,
    LOUD_PEAK,
    PLAYOUT,
    SAMPLE_RATE,
    CallerReply,
    CallRecording,
    Clock,
    PlanMixer,
    Playout,
    Stamper,
    caller_voice,
)
from yaksh.caller.lag import LagSampler
from yaksh.caller.listen import AudioTap, LiveAudio
from yaksh.caller.pipeline import CallerKeys, CallState, Persona, converse
from yaksh.caller.transcript import TranscriptBuilder, WireTap
from yaksh.caller.turn_models import TurnModels
from yaksh.domain.conversations import (
    CallerSettings,
    CallerUsage,
    CallObserver,
    CallRequest,
    EndReason,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.latency import AgentMedia, CallerReplyTime, CallerReplyWindow, LoopLag

log = logging.getLogger(__name__)

ACK_GRACE_S = 0.2
CHUNK_BYTES = SAMPLE_RATE * 2 // 2
LINEAR = "audio/x-l16"
MULAW = "audio/x-mulaw"


@dataclass
class Connected:
    socket: WebSocket
    stream_id: str
    call_uuid: str
    encoding: str


@dataclass(frozen=True)
class Spoken:
    """What a finished conversation leaves for the work after it."""

    state: CallState
    persona: Persona
    recording: CallRecording
    marks: AudioMarks
    serializer: StreamSerializer


class Checkpoints(FrameProcessor):
    """Before the transport output: stamps each reply's playout and, after every chunk of its
    audio, asks Plivo to report once the audio queued so far has played; each report moves the
    reply's sent mark, so provenance follows what the agent has actually heard."""

    def __init__(self, stream_id: str, transcript: TranscriptBuilder) -> None:
        super().__init__(enable_direct_mode=True)
        self._stream_id = stream_id
        self._transcript = transcript
        self._stamper = Stamper()
        self._reply = 0
        self._pending: dict[str, tuple[Playout, int]] = {}

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is not FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, TTSStartedFrame):
            self._reply += 1
            self._pending.clear()
        if isinstance(frame, TTSAudioRawFrame):
            for piece in pieces(frame):
                self._stamper.stamp(piece, self.get_clock().get_time())
                await self.push_frame(piece, direction)
                await self._mark()
            return
        self._stamper.stamp(frame, self.get_clock().get_time())
        await self.push_frame(frame, direction)
        if isinstance(frame, TTSStoppedFrame):
            await self._mark()

    async def _mark(self) -> None:
        playout = self._stamper.arriving
        if playout is None or playout.arrived == 0:
            return
        name = f"{self._reply}:{playout.arrived}"
        if name in self._pending:
            return
        self._pending[name] = (playout, playout.arrived)
        await self.push_frame(
            OutputTransportMessageFrame(
                {"event": "checkpoint", "streamId": self._stream_id, "name": name}
            )
        )

    def played(self, name: str) -> None:
        pending = self._pending.pop(name, None)
        if pending is None:
            return
        playout, through = pending
        playout.played(through)
        self._transcript.audio_progressed()


class KeyPresses(FrameProcessor):
    """Before the transport output: sends the persona's key presses to Plivo as sendDTMF
    messages. The websocket transport has no DTMF of its own and would play them as tones."""

    def __init__(self) -> None:
        super().__init__(enable_direct_mode=True)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, OutputDTMFUrgentFrame):
            frame = OutputTransportMessageUrgentFrame(
                {"event": "sendDTMF", "dtmf": frame.to_string()}
            )
        await self.push_frame(frame, direction)


def pieces(frame: TTSAudioRawFrame) -> list[TTSAudioRawFrame]:
    """A reply's audio in slices short enough for a checkpoint after each."""
    if len(frame.audio) <= CHUNK_BYTES:
        return [frame]
    return [
        TTSAudioRawFrame(
            audio=frame.audio[start : start + CHUNK_BYTES],
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
            context_id=frame.context_id,
        )
        for start in range(0, len(frame.audio), CHUNK_BYTES)
    ]


def plivo_ms(timestamp: Any) -> int | None:
    """Plivo's media timestamp: Unix milliseconds, sent as a string."""
    try:
        return int(timestamp)
    except TypeError, ValueError:
        return None


class StreamSerializer(FrameSerializer):
    """Plivo's stream protocol in the encoding the stream opened with, plus the reports Yaksh
    listens for."""

    def __init__(
        self,
        stream_id: str,
        encoding: str,
        clock: Clock,
        observer: CallObserver,
        checkpoints: Checkpoints,
        recording: CallRecording,
    ) -> None:
        super().__init__()
        self._stream_id = stream_id
        self._linear = encoding.split(";")[0].strip() == LINEAR
        self._clock = clock
        self._observer = observer
        self._checkpoints = checkpoints
        self._recording = recording
        self._quiet = GAP_BYTES
        self.stopped = asyncio.Event()
        self.failed = asyncio.Event()
        self.failure: str | None = None

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            self._event(WireEventKind.CLEAR_AUDIO)
            return json.dumps({"event": "clearAudio", "streamId": self._stream_id})
        if isinstance(frame, AudioRawFrame):
            if not frame.audio:
                return None
            self._recording.caller(frame.audio, self._clock.ms())
            audio = frame.audio if self._linear else audioop.lin2ulaw(frame.audio, 2)
            media = {
                "contentType": LINEAR if self._linear else MULAW,
                "sampleRate": SAMPLE_RATE,
                "payload": base64.b64encode(audio).decode(),
            }
            return json.dumps({"event": "playAudio", "media": media})
        if isinstance(frame, OutputTransportMessageFrame | OutputTransportMessageUrgentFrame):
            return None if self.should_ignore_frame(frame) else json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError, TypeError:
            return None
        if not isinstance(message, dict):
            return None
        match message.get("event"):
            case "media":
                media = message.get("media") or {}
                payload = media.get("payload")
                if not payload:
                    return None
                raw = base64.b64decode(payload)
                pcm = raw if self._linear else audioop.ulaw2lin(raw, 2)
                self._heard(pcm)
                self._recording.agent(pcm, self._clock.ms(), plivo_ms(media.get("timestamp")))
                return InputAudioRawFrame(audio=pcm, sample_rate=SAMPLE_RATE, num_channels=1)
            case "playedStream":
                self._checkpoints.played(str(message.get("name")))
            case "stop":
                self._event(WireEventKind.STOP)
                self.stopped.set()
            case "playFailed" if not self.stopped.is_set():
                self._event(WireEventKind.CALLER_ERROR)
                log.warning("plivo could not play audio: %s", message.get("reason"))
                self.failure = (
                    self.failure or f"plivo could not play audio: {message.get('reason')}"
                )
            case "error":
                self._event(WireEventKind.CALLER_ERROR)
                fatal = f"plivo reported an error: {message.get('reason')}"
                self.failure = (
                    fatal if self.failure is None else f"{fatal}; before it, {self.failure}"
                )
                self.failed.set()
        return None

    def _heard(self, pcm: bytes) -> None:
        """The first packet louder than LOUD_PEAK after a quiet stretch: sound from the agent's
        side started, which may be speech, music, a beep or line noise."""
        if audioop.max(pcm, 2) > LOUD_PEAK:
            if self._quiet >= GAP_BYTES:
                self._event(WireEventKind.AGENT_AUDIO)
            self._quiet = 0
        else:
            self._quiet += len(pcm)

    def _event(self, kind: WireEventKind) -> None:
        self._observer.wire_event(WireEvent(kind=kind, at_ms=self._clock.ms()))


class AudioMarks(FrameProcessor):
    """After the transport output: when the persona's audio starts and stops going out. It
    keeps each reply with its playout, which its spoken words carry. A reply that the TTS
    finished stops when the output handles its TTSStoppedFrame, which then follows the stop at
    once. A reply that the call or a barge-in cut off has no such frame."""

    def __init__(self, clock: Clock, observer: CallObserver) -> None:
        super().__init__(enable_direct_mode=True)
        self._clock = clock
        self._observer = observer
        self._just_stopped = False
        self._starting: Playout | None = None
        """The playout of the latest reply that the TTS started."""
        self.replies: list[CallerReply] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM:
            just_stopped, self._just_stopped = self._just_stopped, False
            if isinstance(frame, TTSStartedFrame):
                self._starting = frame.metadata.get(PLAYOUT)
            elif isinstance(frame, BotStartedSpeakingFrame):
                if self._starting is not None and self._starting.audio_index is None:
                    self._starting.audio_index = len(self.replies)
                self.replies.append(CallerReply(self._mark(WireEventKind.CALLER_AUDIO_START)))
            elif isinstance(frame, BotStoppedSpeakingFrame):
                ended = self._mark(WireEventKind.CALLER_AUDIO_END)
                if self.replies and self.replies[-1].end_ms is None:
                    self.replies[-1].end_ms = ended
                    self._just_stopped = True
            elif isinstance(frame, TTSTextFrame) and self.replies and not self.replies[-1].playout:
                self.replies[-1].playout = frame.metadata.get(PLAYOUT)
            elif isinstance(frame, TTSStoppedFrame) and just_stopped:
                self.replies[-1].playout = frame.metadata.get(PLAYOUT)
                self.replies[-1].finished = True
        await self.push_frame(frame, direction)

    def _mark(self, kind: WireEventKind) -> int:
        at = self._clock.ms()
        self._observer.wire_event(WireEvent(kind=kind, at_ms=at))
        return at


async def settled() -> None:
    """Reports for audio that played just before a cut are still in flight; give them a moment."""
    await asyncio.sleep(ACK_GRACE_S)


@dataclass(frozen=True)
class Ended:
    at_ms: int
    """When the conversation ended, on the call clock."""
    started_ms: int
    """When the call's audio starts, on the call clock; the recording starts here."""


@dataclass(frozen=True)
class Heard:
    """What a finished conversation leaves for the call's outcome."""

    end_reason: EndReason | None
    error: str | None
    caller_reason: str | None
    serializer_failure: str | None
    recording: bytes | None
    agent_media: AgentMedia | None
    caller_replies: list[CallerReplyWindow]
    caller_voice: bytes | None
    caller_settings: CallerSettings
    caller_usage: CallerUsage
    caller_reply_times: list[CallerReplyTime]
    loop_lag: LoopLag | None


@dataclass(frozen=True)
class ConversationStart:
    request: CallRequest
    keys: CallerKeys
    observer: CallObserver
    stop: asyncio.Event
    clock: Clock
    dialed: Connected
    own: asyncio.Future[bytes] | None
    """The persona's own voicemail greeting, being spoken."""
    connected_ms: int


class Conversation(Protocol):
    async def ended(self) -> Ended: ...

    def cancel(self) -> None:
        """End the conversation as a stopped worker does: as worker_stopped, with its result."""
        ...

    async def heard(self) -> Heard: ...

    async def close(self) -> None:
        """Free what the conversation holds, also after a failure or a cancel."""
        ...


class Seat(Protocol):
    """A place for one conversation, taken when the call is claimed, so that it is ready by
    the time the stream opens."""

    async def start(self, start: ConversationStart) -> Conversation: ...

    async def release(self) -> None:
        """Give back a seat whose conversation never started; after `start`, nothing to do."""
        ...


class Conversations(Protocol):
    def reserve(self) -> Seat: ...


async def hold_conversation(start: ConversationStart, live: LiveAudio, turns: TurnModels) -> Spoken:
    """Build the caller around the stream and hold the conversation until it ends. When the
    persona's voicemail or call screener answers, it starts at connect in place of the
    persona."""
    request, observer, clock, dialed = start.request, start.observer, start.clock, start.dialed
    log.info(
        "stream %s for conversation %s, call %s, %s",
        dialed.stream_id,
        request.conversation_id,
        dialed.call_uuid,
        dialed.encoding,
    )
    transcript = TranscriptBuilder(clock, observer)
    checkpoints = Checkpoints(dialed.stream_id, transcript)
    recording = CallRecording()
    marks = AudioMarks(clock, observer)
    serializer = StreamSerializer(
        dialed.stream_id, dialed.encoding, clock, observer, checkpoints, recording
    )
    transport = FastAPIWebsocketTransport(
        dialed.socket,
        FastAPIWebsocketParams(
            serializer=serializer,
            add_wav_header=False,
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=SAMPLE_RATE,
            audio_out_10ms_chunks=2,
            audio_out_end_silence_secs=0,
            audio_out_mixer=PlanMixer(request.sound_plan) if request.sound_plan.layers else None,
        ),
    )
    state = CallState()
    disconnected = asyncio.Event()
    persona = Persona(
        start.keys,
        request,
        clock,
        observer,
        transcript,
        transport_input=transport.input(),
        transport_output=transport.output(),
        before_output=[checkpoints, KeyPresses()],
        after_output=[marks, WireTap(transcript, settled)],
        state=state,
        turn_models=turns,
        observers=[AudioTap(transport.input(), transport.output(), live)],
    )

    machine: asyncio.Task[None] | None = None

    @transport.event_handler("on_client_connected")
    async def on_connected(_transport: Any, _socket: Any) -> None:
        nonlocal machine
        if request.answering is not None:
            script = AnsweringScript(
                request.answering, persona, state, transcript, observer, clock, start.own
            )
            machine = asyncio.create_task(script.run())
        elif not request.agent.agent_speaks_first:
            await persona.speak_first()

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_transport: Any, _socket: Any) -> None:
        disconnected.set()

    greeting = None
    if request.agent.agent_speaks_first and request.answering is None:
        greeting = asyncio.create_task(persona.greet_if_silent())
    try:
        await converse(
            persona,
            state,
            start.stop,
            {
                serializer.stopped: EndReason.STREAM_ENDED,
                disconnected: EndReason.STREAM_ENDED,
                serializer.failed: EndReason.ERROR,
            },
        )
    finally:
        for task in (greeting, machine):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    return Spoken(state, persona, recording, marks, serializer)


async def hear(spoken: Spoken, started_ms: int, loop_lag: LoopLag | None) -> Heard:
    """Build the call's audio and read what the finished conversation left."""
    recording = await asyncio.to_thread(spoken.recording.to_wav, started_ms)
    voice, caller_replies = await asyncio.to_thread(caller_voice, spoken.marks.replies)
    return Heard(
        end_reason=spoken.state.end_reason,
        error=spoken.state.error,
        caller_reason=spoken.state.caller_reason,
        serializer_failure=spoken.serializer.failure,
        recording=recording,
        agent_media=spoken.recording.agent_media(started_ms),
        caller_replies=caller_replies,
        caller_voice=voice,
        caller_settings=spoken.persona.settings,
        caller_usage=spoken.persona.usage.usage(),
        caller_reply_times=spoken.persona.reply_times.replies,
        loop_lag=loop_lag,
    )


class LocalConversations:
    """Holds each conversation in this process, on its event loop, with one set of turn models
    for all of them. A conversation here needs no reservation, so this is its own seat."""

    def __init__(self, turns: TurnModels, database_url: str) -> None:
        self._turns = turns
        self._database_url = database_url

    def reserve(self) -> Seat:
        return self

    async def start(self, start: ConversationStart) -> Conversation:
        return LocalConversation(start, self._turns, self._database_url)

    async def release(self) -> None:
        pass


class LocalConversation:
    def __init__(self, start: ConversationStart, turns: TurnModels, database_url: str) -> None:
        self._connected_ms = start.connected_ms
        self._clock = start.clock
        self._live = LiveAudio(database_url, start.request.conversation_id)
        self._lag = LagSampler(start.clock.ms)
        self._task = asyncio.ensure_future(hold_conversation(start, self._live, turns))
        self._loop_lag: LoopLag | None = None
        self._started_ms = start.connected_ms

    async def ended(self) -> Ended:
        spoken = await asyncio.shield(self._task)
        self._loop_lag = self._lag.stop()
        self._started_ms = spoken.recording.start_ms(self._connected_ms)
        return Ended(self._clock.ms(), self._started_ms)

    def cancel(self) -> None:
        self._task.cancel()

    async def heard(self) -> Heard:
        await self._live.close()
        return await hear(self._task.result(), self._started_ms, self._loop_lag)

    async def close(self) -> None:
        self._lag.stop()
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        await self._live.close()
