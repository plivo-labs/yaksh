import asyncio
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from truman.domain.agents import AgentConfig
from truman.domain.languages import Language
from truman.domain.scenarios import Fact
from truman.domain.voices import VoiceSettings


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
    """Who or what ended the conversation, as Truman observed it."""

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
    """A failure on Truman's side or on the line; a run tries these again."""
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
    CALLER_AUDIO_START = "caller_audio_start"
    """Truman's output started sending caller audio; not proof it played on the line."""
    CALLER_AUDIO_END = "caller_audio_end"
    AGENT_AUDIO = "agent_audio"
    CLEAR_AUDIO = "clear_audio"
    SILENCE_GREETING = "silence_greeting"
    STOP = "stop"
    CALLER_ERROR = "caller_error"
    TRIGGER_SENT = "trigger_sent"
    """Truman sent the outbound agent's trigger; the detail holds the result."""
    WAITING_FOR_CALL = "waiting_for_call"


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    text: str
    started_at_ms: int
    ended_at_ms: int
    provenance: Provenance | None = None
    scripted: bool = False
    """Fixed text Truman spoke for the caller, such as the idle nudge, not model output."""


class WireEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: WireEventKind
    at_ms: int
    detail: str | None = None


class Validity(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    reasons: list[str] = Field(default_factory=list)


class CallerClaim(BaseModel):
    """What the caller model said when it hung up. A claim, not a verdict on the agent."""

    model_config = ConfigDict(frozen=True)

    success: bool
    reason: str


class Transcript(BaseModel):
    turns: list[Turn] = Field(default_factory=list)
    wire_events: list[WireEvent] = Field(default_factory=list)
    validity: Validity | None = None


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: uuid.UUID
    persona_id: uuid.UUID
    scenario_id: uuid.UUID
    max_duration_s: int | None = Field(default=None, ge=10, le=1800)


class IncomingCall(BaseModel):
    """A call Plivo delivers to one of Truman's numbers, as its answer webhook describes it."""

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
    nudge: str
    caller_language: Language
    voice: VoiceSettings
    caller_number: str
    max_duration_s: int
    agent_data: list[Fact] = []
    pickup: str = "Hello?"
    """What the caller says on answering an outbound agent that waits for the callee."""
    accept_calls_until: datetime | None = None
    """Outbound: when the window for the agent's call closes."""
    output_dir: Path


class CallOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    connected: bool
    end_reason: EndReason
    caller_error: str | None = None
    caller_claim: CallerClaim | None = None
    talk_ms: int | None = None
    """From the moment the call connected until the conversation ended, on the caller's clock."""
    recording_path: Path | None = None
    call_uuid: str | None = None


class CallObserver(Protocol):
    def turn(self, turn: Turn) -> None: ...

    def wire_event(self, event: WireEvent) -> None: ...


class Caller(Protocol):
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome: ...
