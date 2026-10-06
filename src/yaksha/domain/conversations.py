import asyncio
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from yaksha.domain.agents import AgentConfig
from yaksha.domain.background_noise import NoiseMix
from yaksha.domain.languages import Language
from yaksha.domain.latency import AgentMedia, CallerReplyWindow, LoopLag
from yaksha.domain.scenarios import Fact
from yaksha.domain.voices import VoiceSettings


class Channel(StrEnum):
    VOICE = "voice"


class ConversationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    ENDING = "ending"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID = "invalid"
    CANCELLED = "cancelled"


class EndReason(StrEnum):
    """Who or what ended the conversation, as Yaksha observed it."""

    USER_REQUEST = "user_request"
    CALLER_HANGUP = "caller_hangup"
    AGENT_HANGUP = "agent_hangup"
    """Plivo reported that the agent's side hung up."""
    AGENT_SILENT = "agent_silent"
    NO_ANSWER = "no_answer"
    STREAM_ENDED = "stream_ended"
    """The audio stream stopped and Plivo did not say which side ended the call."""
    DURATION_LIMIT = "duration_limit"
    ERROR = "error"
    WORKER_STOPPED = "worker_stopped"
    LEASE_LOST = "lease_lost"
    """The worker could not keep its claim on the conversation, so it stopped the call."""
    TRIGGER_FAILED = "trigger_failed"
    """The outbound agent's system refused the trigger, or it could not be sent."""
    NO_CALL = "no_call"
    """The outbound agent did not call within its dial window."""
    TURN_LIMIT = "turn_limit"
    """The caller answered its most agent turns, said goodbye and hung up."""


ACTIVE_STATUSES = frozenset(
    {ConversationStatus.QUEUED, ConversationStatus.RUNNING, ConversationStatus.ENDING}
)
LIVE_STATUSES = frozenset({ConversationStatus.RUNNING, ConversationStatus.ENDING})


class OutcomeGroup(StrEnum):
    """How a conversation went, from its status and end reason only. Before any judge, the
    groups say what happened, not who is at fault."""

    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DID_NOT_CONNECT = "did_not_connect"
    ERROR = "error"
    """A failure on Yaksha's side or on the line; a run tries these again."""
    CANCELLED = "cancelled"


NOT_CONNECTED = frozenset(
    {EndReason.NO_ANSWER, EndReason.NO_CALL, EndReason.TRIGGER_FAILED, EndReason.AGENT_HANGUP}
)
"""End reasons of a failed conversation whose call never connected. A failed conversation
ends with agent_hangup only when the agent hung up before the audio started."""


def outcome_group(status: ConversationStatus, end_reason: EndReason | None) -> OutcomeGroup:
    if status is ConversationStatus.CANCELLED or end_reason is EndReason.USER_REQUEST:
        return OutcomeGroup.CANCELLED
    if status is ConversationStatus.QUEUED:
        return OutcomeGroup.WAITING
    if status in LIVE_STATUSES:
        return OutcomeGroup.IN_PROGRESS
    if status is ConversationStatus.COMPLETED:
        return OutcomeGroup.COMPLETED
    if status is ConversationStatus.FAILED and end_reason in NOT_CONNECTED:
        return OutcomeGroup.DID_NOT_CONNECT
    return OutcomeGroup.ERROR


class Role(StrEnum):
    AGENT = "agent"
    CALLER = "caller"


class Provenance(StrEnum):
    TRANSMITTED = "transmitted"
    """Plivo reported the audio of these words as played."""
    CUT = "cut"
    """Agent-side voice started a turn while these words were due, and Plivo did not report
    them played in full."""
    UNCONFIRMED = "unconfirmed"
    """No play report covers these words, and no barge-in stopped them."""


class WireEventKind(StrEnum):
    CONNECT_STARTED = "connect_started"
    RINGING = "ringing"
    ANSWERED = "answered"
    CONNECTED = "connected"
    """The call's audio started: when Plivo's stream opened, or earlier when the agent's first
    frame is stamped before that. Talk time and the recording count from here."""
    CALLER_AUDIO_START = "caller_audio_start"
    """Yaksha's output started sending caller audio; not proof it played on the line."""
    CALLER_AUDIO_END = "caller_audio_end"
    AGENT_AUDIO = "agent_audio"
    CLEAR_AUDIO = "clear_audio"
    SILENCE_GREETING = "silence_greeting"
    STOP = "stop"
    CALLER_ERROR = "caller_error"
    END_CALL = "end_call"
    """The caller's model ended the call; the detail is its reason."""
    TURN_LIMIT = "turn_limit"
    """The caller answered its most agent turns and starts the goodbye."""
    TRIGGER_SENT = "trigger_sent"
    """Yaksha sent the outbound agent's trigger; the detail holds the result."""
    WAITING_FOR_CALL = "waiting_for_call"


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    text: str
    started_at_ms: int
    ended_at_ms: int
    provenance: Provenance | None = None
    scripted: bool = False
    """Fixed text Yaksha spoke for the caller, such as the idle nudge, not model output."""


class WireEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: WireEventKind
    at_ms: int
    detail: str | None = None


class Validity(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    reasons: list[str] = Field(default_factory=list)


class Transcript(BaseModel):
    turns: list[Turn] = Field(default_factory=list)
    wire_events: list[WireEvent] = Field(default_factory=list)
    validity: Validity | None = None
    stream_opened_ms: int | None = None
    """When Yaksha's stream opened. A `connected` event can move earlier, to the agent's
    first audio, but the stream opened here."""
    loop_lag: LoopLag | None = None
    """How late the worker's event loop ran while the call was live."""
    recording_start_ms: int | None = None
    """Where the recording and the agent's channel start on the call's clock."""
    agent_media: AgentMedia | None = None
    caller_replies: list[CallerReplyWindow] | None = None
    """Each caller reply, with where its own audio sits in the caller voice file."""

    @property
    def connected(self) -> bool:
        """The call's audio started. The event is in the record even when the call later
        failed, as when its worker stopped."""
        return any(event.kind is WireEventKind.CONNECTED for event in self.wire_events)


class LineFacts(BaseModel):
    """Plivo's hangup report for a call that connected, as Plivo wrote it: who hung up, why,
    and how long the call lasted. The times are Plivo's text; no time zone is assumed."""

    model_config = ConfigDict(frozen=True)

    hangup_source: str | None = None
    hangup_cause: str | None = None
    duration_s: int | None = None
    bill_duration_s: int | None = None
    answer_time: str | None = None
    end_time: str | None = None


class CallerSettings(BaseModel):
    """What the caller ran: the models behave differently, so a result names them."""

    model_config = ConfigDict(frozen=True)

    llm_model: str
    reasoning_effort: str | None
    """The effort configured for the caller's model; None leaves it to Pipecat, which asks a
    reasoning model that accepts it for none."""
    stt_model: str
    tts_model: str
    voice: VoiceSettings


class CallerUsage(BaseModel):
    """What the caller's services consumed, as they reported it. A service that reported
    nothing leaves its fields None: unknown, not zero."""

    model_config = ConfigDict(frozen=True)

    llm_prompt_tokens: int | None = None
    llm_completion_tokens: int | None = None
    llm_reasoning_tokens: int | None = None
    llm_cache_read_tokens: int | None = None
    llm_cache_creation_tokens: int | None = None
    stt_audio_seconds: float | None = None
    tts_characters: int | None = None


class IncomingCall(BaseModel):
    """A call Plivo delivers to one of Yaksha's numbers, as its answer webhook describes it."""

    model_config = ConfigDict(frozen=True)

    to_number: str
    from_number: str
    call_uuid: str


class Admission(BaseModel):
    """An incoming call accepted for the outbound conversation waiting on its number."""

    model_config = ConfigDict(frozen=True)

    conversation_id: uuid.UUID
    max_duration_s: int


class CallRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: uuid.UUID
    agent: AgentConfig
    instructions: str
    first_words: str
    """What the caller says first when it speaks first."""
    nudge: str
    caller_language: Language
    voice: VoiceSettings
    background_noise: NoiseMix | None = None
    """The sound the caller's audio is mixed with; None sends the voice alone."""
    caller_number: str
    max_duration_s: int
    max_turns: int
    """How many agent turns the caller answers; at the next one it says `goodbye` and hangs
    up."""
    goodbye: str
    agent_data: list[Fact] = []
    accept_calls_until: datetime | None = None
    """Outbound: when the window for the agent's call closes."""
    output_dir: Path


class CallOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    connected: bool
    end_reason: EndReason
    caller_error: str | None = None
    caller_reason: str | None = None
    """Why the caller ended the call, in its own words. Whether the agent passed is a judge's
    call, never the caller's."""
    talk_ms: int | None = None
    """From the moment the call connected until the conversation ended, on the caller's clock."""
    recording_path: Path | None = None
    stream_opened_ms: int | None = None
    caller_settings: CallerSettings | None = None
    caller_usage: CallerUsage | None = None
    line_facts: LineFacts | None = None
    loop_lag: LoopLag | None = None
    recording_start_ms: int | None = None
    agent_media: AgentMedia | None = None
    caller_replies: list[CallerReplyWindow] | None = None
    caller_voice_path: Path | None = None
    call_uuid: str | None = None


class CallObserver(Protocol):
    def turn(self, turn: Turn) -> None: ...

    def wire_event(self, event: WireEvent) -> None:
        """A second `connected` event replaces the first: the time is final only when the call
        ends."""
        ...


class Caller(Protocol):
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome: ...
