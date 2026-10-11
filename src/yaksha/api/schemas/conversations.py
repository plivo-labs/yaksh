import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from yaksha.domain.agents import Direction
from yaksha.domain.conversations import (
    Channel,
    ConversationStatus,
    EndReason,
    Turn,
    Validity,
    WireEvent,
)
from yaksha.domain.evaluations import (
    DecidedBy,
    EvaluationState,
    ItemRole,
    Metric,
    Outcome,
    UnsureKind,
    Verdict,
)
from yaksha.domain.languages import Language
from yaksha.domain.latency import Latency, Reply
from yaksha.domain.scenarios import PlayedScenario
from yaksha.domain.surroundings import Layer, NoiseSound, SoundPlan, SpeakerKind, Surroundings
from yaksha.simulation.surroundings import clip_by_file


class LatencySummary(BaseModel):
    """The agent's response times in one call: nearest-rank percentiles over the measured
    replies, how many replies there were, and how many of them talked over the caller."""

    p50_ms: int | None
    p90_ms: int | None
    replies: int
    talked_over: int

    @classmethod
    def of(cls, latency: Latency) -> LatencySummary:
        return cls(
            p50_ms=latency.p50_ms,
            p90_ms=latency.p90_ms,
            replies=len(latency.replies),
            talked_over=sum(reply.response_ms is None for reply in latency.replies),
        )


class TurnRead(Turn):
    response_ms: int | None = None
    """On an agent turn that starts a reply: how long the agent made the caller wait."""
    talked_over: bool = False
    """On an agent turn that starts a reply: the agent began before the caller finished."""


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_version: int
    agent_name: str
    persona_id: uuid.UUID
    persona_version_id: uuid.UUID
    persona_version: int
    persona_name: str
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    scenario_version: int
    scenario_name: str
    data_set_id: uuid.UUID
    data_set_name: str
    scenario_data_sets: int
    """How many data sets the pinned scenario version holds; the data set's name tells a call
    apart only when it holds more than one."""
    direction: Direction
    language: Language
    channel: Channel
    caller_number: str | None
    agent_caller_id: str | None
    call_uuid: str | None
    max_duration_s: int
    max_turns: int
    surroundings: Surroundings
    status: ConversationStatus
    end_reason: EndReason | None
    failure_reason: str | None
    started_at: datetime | None
    ended_at: datetime | None
    talk_ms: int | None
    latency: LatencySummary | None
    """None when the call was not measured, or when the agent never spoke."""
    evaluation: EvaluationState | None
    """None for a conversation with no evaluation: one not ended yet, or cancelled before its
    call connected."""
    recording_url: str | None
    caller_reason: str | None
    run_id: uuid.UUID
    repeat: int
    attempt: int
    retry_of: uuid.UUID | None
    created_at: datetime


class SpokenLine(BaseModel):
    at_s: float
    """When the line starts, in seconds from the start of the call's audio."""
    text: str


class SoundRead(BaseModel):
    """One sound the call played behind the caller."""

    file: str
    sound: NoiseSound | None
    """The noise that played, or None for a second speaker's clip."""
    speaker: SpeakerKind | None
    start_s: float
    end_s: float | None
    """None: until the call ended."""
    speaker_lines: list[SpokenLine]
    """For a background speaker's clip, what it says; empty for a noise."""

    @classmethod
    def of(cls, layer: Layer) -> SoundRead:
        clip = clip_by_file(layer.file)
        return cls(
            file=layer.file,
            sound=layer.sound,
            speaker=layer.speaker,
            start_s=layer.start_s,
            end_s=layer.end_s,
            speaker_lines=[]
            if clip is None
            else [
                SpokenLine(at_s=layer.start_s + line.start_s, text=line.text) for line in clip.lines
            ],
        )

    @classmethod
    def all_of(cls, saved: dict[str, Any]) -> list[SoundRead]:
        return [cls.of(layer) for layer in SoundPlan.model_validate(saved).layers]


class ConversationRead(ConversationSummary):
    instructions: str
    sounds: list[SoundRead]
    """What the call played behind the caller, as planned before it started; sounds planned
    after the call ended were not heard."""
    scenario: PlayedScenario
    transcript: list[TurnRead]
    replies: list[Reply]
    """Each reply's start point and the agent's first speech, on the call's clock."""
    wire_events: list[WireEvent]
    validity: Validity | None
    retried_as: uuid.UUID | None


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_key: str
    subject: str
    """The criterion's text or the rule's name."""
    role: ItemRole
    decided_by: DecidedBy
    machine_outcome: Outcome
    unsure_kind: UnsureKind | None
    effective_outcome: Outcome
    """After people's labels; the machine outcome while there are none."""
    effective_unsure_kind: UnsureKind | None
    answer: dict[str, Any] | None
    """The judge's answer: its evidence with turn numbers, its reasoning and its verdict."""
    error_reason: str | None
    caller_effect: dict[str, Any] | None
    """How Yaksha's caller affected this criterion, by the caller check."""
    jev_choice: str | None
    """What Jev chose when it answered the item first; a Jev pass has no other answer."""
    jev_probabilities: dict[str, float] | None


class ConversationEvaluation(BaseModel):
    evaluation: EvaluationState | None
    """None for a conversation with no evaluation."""
    failure: str | None
    """Why the last attempt failed, while it is tried again and after it ended failed."""
    metrics: dict[str, Metric]
    """By metric key; empty until the evaluation is done."""
    scenario_verdict: Verdict | None
    """From the criteria; None when the call was not judged."""
    conversation_verdict: Verdict | None
    """The criteria and the deciding agent rules."""
    effective_scenario_verdict: Verdict | None
    effective_conversation_verdict: Verdict | None
    items: list[ItemRead]
