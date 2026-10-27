import asyncio
import uuid
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from yaksh.domain.agents import AgentConfig, Transport
from yaksh.domain.answering import AnsweredBy, AnsweringPlan, MachineLine
from yaksh.domain.languages import Language
from yaksh.domain.latency import AgentMedia, CallerReplyWindow, LoopLag
from yaksh.domain.scenarios import Fact
from yaksh.domain.settings import AppSettings, CallerModel
from yaksh.domain.surroundings import SoundPlan
from yaksh.domain.voices import VoiceSettings


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
    """Who or what ended the conversation, as Yaksh observed it."""

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
    START_REFUSED = "start_refused"
    """A text agent refused the first request with a 4xx: its URL or headers are wrong."""
    VOICEMAIL_ENDED = "voicemail_ended"
    """The persona's voicemail stopped recording, or its mailbox was full, and hung up."""
    SCREENER_ENDED = "screener_ended"
    """The persona's call screener hung up: it sent a reply, the persona declined, or the
    agent did not answer it."""


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
    """A failure on Yaksh's side or on the line; a run tries these again."""
    CANCELLED = "cancelled"


NOT_CONNECTED = frozenset(
    {
        EndReason.NO_ANSWER,
        EndReason.NO_CALL,
        EndReason.TRIGGER_FAILED,
        EndReason.AGENT_HANGUP,
        EndReason.START_REFUSED,
    }
)
"""End reasons of a failed conversation whose call never connected. A failed conversation
ends with agent_hangup only when the agent hung up before the audio started."""


def judges_score(status: ConversationStatus, end_reason: EndReason | None) -> bool:
    """The judges score a call that completed and that no user ended; another ended call gets
    only its metrics."""
    return status is ConversationStatus.COMPLETED and end_reason is not EndReason.USER_REQUEST


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
    frame is stamped before that. Talk time and the recording count from here. For a text
    agent, its first reply; the detail is the session id it made."""
    CALLER_AUDIO_START = "caller_audio_start"
    """Yaksh's output started sending caller audio; not proof it played on the line."""
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
    """Yaksh sent the outbound agent's trigger; the detail holds the result."""
    WAITING_FOR_CALL = "waiting_for_call"
    CALLER_SOUND = "caller_sound"
    """A sound of the persona's phone, such as the voicemail's tone; the detail names it and
    its length."""
    HOLD_STARTED = "hold_started"
    """The call screener put the agent on hold; the detail is the hold in ms."""
    HANDOVER = "handover"
    """The persona picked up after its call screener."""


class ToolItem(BaseModel):
    """A tool the text agent called in its turn, as the agent reported it."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: str
    output: str | None = None


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    text: str
    started_at_ms: int
    ended_at_ms: int
    provenance: Provenance | None = None
    scripted: bool = False
    """Fixed text Yaksh spoke for the caller, such as the idle nudge, not model output."""
    machine: MachineLine | None = None
    """A recorded line of the persona's voicemail or call screener, not the persona."""
    dtmf: bool = False
    """Keys the caller pressed on its phone keypad (DTMF), not words it spoke. Plivo reports no
    play for keys, so a key press has no provenance and counts as sent."""
    tools: list[ToolItem] = Field(default_factory=list)
    """The text agent's tool calls in this turn, in its order."""


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
    """When Yaksh's stream opened. A `connected` event can move earlier, to the agent's
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


def picked_up(events: Iterable[WireEvent]) -> bool:
    """The persona picked up after its call screener."""
    return any(event.kind is WireEventKind.HANDOVER for event in events)


def voicemail_answered(turns: Iterable[Turn]) -> bool:
    """The persona's voicemail played its greeting or its full-mailbox line."""
    return any(turn.machine in (MachineLine.GREETING, MachineLine.MAILBOX_FULL) for turn in turns)


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
    """The effort the caller sent, None for none. Older records hold the configured effort
    instead, where None meant the lowest effort that Pipecat lists for the model."""
    scenario_model: bool = False
    """The scenario chose the model and effort, not the settings."""
    stt_model: str | None = None
    """None for a text agent, which Yaksh reads with no speech-to-text."""
    stt_language: str | None = None
    """The language setting the speech-to-text heard the agent with; None on calls from before
    Yaksh recorded it."""
    tts_model: str | None = None
    voice: VoiceSettings | None = None


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
    """A call Plivo delivers to one of Yaksh's numbers, as its answer webhook describes it."""

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
    transport: Transport
    """How Yaksh reaches the agent: its run's transport."""
    instructions: str
    first_words: str
    """What the caller says first when it speaks first."""
    nudge: str
    caller_language: Language
    voice: VoiceSettings
    sound_plan: SoundPlan = SoundPlan()
    """The sounds mixed under the caller's voice, with full file paths."""
    caller_number: str | None
    """None for a text agent, which Yaksh reaches with no number."""
    max_duration_s: int
    max_turns: int
    """How many agent turns the caller answers; at the next one it says `goodbye` and hangs
    up."""
    goodbye: str
    agent_data: list[Fact] = []
    accept_calls_until: datetime | None = None
    """Outbound: when the window for the agent's call closes."""
    app_settings: AppSettings
    """The settings when the call started; a change during the call does not reach it."""
    caller: CallerModel
    """The caller's model: the scenario's, else the settings'."""
    scenario_model: bool = False
    answered_by: AnsweredBy = AnsweredBy.CALLER
    answering: AnsweringPlan | None = None
    """What the persona's phone plays before or in place of the persona; None when the persona
    answers."""


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
    recording: bytes | None = Field(default=None, repr=False)
    """The call as a stereo WAV: the agent on the left channel, the caller on the right."""
    stream_opened_ms: int | None = None
    caller_settings: CallerSettings | None = None
    caller_usage: CallerUsage | None = None
    line_facts: LineFacts | None = None
    loop_lag: LoopLag | None = None
    recording_start_ms: int | None = None
    agent_media: AgentMedia | None = None
    caller_replies: list[CallerReplyWindow] | None = None
    caller_voice: bytes | None = Field(default=None, repr=False)
    """Each caller reply's own audio, back to back, as a mono WAV."""
    call_uuid: str | None = None
    trigger_response: str | None = None
    """The body of the outbound agent's trigger response, secrets masked: where a provider
    names the call it started."""
    clock_started_at: datetime | None = None
    """A phone call that connected: the wall time when the call's clock read 0."""


def audio_key(conversation_id: uuid.UUID, file_name: str) -> str:
    """Where a call's audio file is kept in the file store."""
    return f"recordings/{conversation_id}/{file_name}"


class StoredAudio(BaseModel):
    """The keys of a call's audio files in the file store; None for a file not stored."""

    model_config = ConfigDict(frozen=True)

    recording_key: str | None = None
    caller_voice_key: str | None = None


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
