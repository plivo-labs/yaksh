import asyncio
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from truman.domain.agents import AgentConfig
from truman.domain.languages import Language
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
    """Plivo reported that the called side, the agent, hung up."""
    AGENT_SILENT = "agent_silent"
    NO_ANSWER = "no_answer"
    STREAM_ENDED = "stream_ended"
    """The audio stream stopped and Plivo did not say which side ended the call."""
    DURATION_LIMIT = "duration_limit"
    ERROR = "error"
    WORKER_STOPPED = "worker_stopped"
    LEASE_LOST = "lease_lost"
    """The worker could not keep its claim on the conversation, so it stopped the call."""


ACTIVE_STATUSES = frozenset(
    {ConversationStatus.QUEUED, ConversationStatus.RUNNING, ConversationStatus.ENDING}
)


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
    CALLER_SPEECH_START = "caller_speech_start"
    CALLER_SPEECH_END = "caller_speech_end"
    AGENT_AUDIO = "agent_audio"
    CLEAR_AUDIO = "clear_audio"
    SILENCE_GREETING = "silence_greeting"
    STOP = "stop"
    CALLER_ERROR = "caller_error"


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
    caller_claim: CallerClaim | None = None


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: uuid.UUID
    persona_id: uuid.UUID
    goal: str = Field(min_length=1, max_length=2000)
    max_duration_s: int | None = Field(default=None, ge=10, le=1800)


class CallRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: uuid.UUID
    agent: AgentConfig
    instructions: str
    nudge: str
    language: Language
    voice: VoiceSettings
    caller_number: str
    max_duration_s: int
    output_dir: Path


class CallOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    connected: bool
    end_reason: EndReason
    caller_error: str | None = None
    caller_claim: CallerClaim | None = None
    recording_path: Path | None = None
    call_uuid: str | None = None


class CallObserver(Protocol):
    def turn(self, turn: Turn) -> None: ...

    def wire_event(self, event: WireEvent) -> None: ...


class Caller(Protocol):
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome: ...
