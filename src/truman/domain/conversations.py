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
    USER_REQUEST = "user_request"
    GOAL_REACHED = "goal_reached"
    GOAL_ABANDONED = "goal_abandoned"
    AGENT_HANGUP = "agent_hangup"
    AGENT_SILENT = "agent_silent"
    NO_ANSWER = "no_answer"
    DURATION_LIMIT = "duration_limit"
    ERROR = "error"
    PROCESS_RESTART = "process_restart"


ACTIVE_STATUSES = frozenset(
    {ConversationStatus.QUEUED, ConversationStatus.RUNNING, ConversationStatus.ENDING}
)


class Role(StrEnum):
    AGENT = "agent"
    CALLER = "caller"


class Provenance(StrEnum):
    TRANSMITTED = "transmitted"
    CUT = "cut"


class WireEventKind(StrEnum):
    CONNECT_STARTED = "connect_started"
    RINGING = "ringing"
    ANSWERED = "answered"
    CONNECTED = "connected"
    CALLER_SPEECH_START = "caller_speech_start"
    CALLER_SPEECH_END = "caller_speech_end"
    AGENT_AUDIO = "agent_audio"
    CLEAR_AUDIO = "clear_audio"
    STOP = "stop"
    CALLER_ERROR = "caller_error"


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    text: str
    started_at_ms: int
    ended_at_ms: int
    provenance: Provenance | None = None


class WireEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: WireEventKind
    at_ms: int


class Validity(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    reasons: list[str] = Field(default_factory=list)


class Transcript(BaseModel):
    turns: list[Turn] = Field(default_factory=list)
    wire_events: list[WireEvent] = Field(default_factory=list)
    validity: Validity | None = None


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
    recording_path: Path | None = None
    call_uuid: str | None = None


class CallObserver(Protocol):
    def turn(self, turn: Turn) -> None: ...

    def wire_event(self, event: WireEvent) -> None: ...


class Caller(Protocol):
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome: ...
