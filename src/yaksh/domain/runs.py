"""Runs: conversations of several scenarios started together against one agent, each scenario
repeated."""

import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from yaksh.domain.agents import Transport
from yaksh.domain.answering import AnsweredBy
from yaksh.domain.conversations import EndReason, OutcomeGroup

RunName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


def listed_once[T](items: list[T] | None, kind: str) -> list[T] | None:
    repeated = [item for item, n in Counter(items or []).items() if n > 1]
    if repeated:
        raise ValueError(f"{kind} {repeated[0]} is listed more than once")
    return items


class RunScenario(BaseModel):
    """A scenario of a run, the personas that call it and the data sets they play. No personas
    is the scenario's own persona; no data sets is every data set of its current version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: uuid.UUID
    persona_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    """In the order their conversations start."""
    data_set_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    """In the order each persona plays them."""
    answered_by: list[AnsweredBy] = Field(default=[AnsweredBy.CALLER], min_length=1)
    """Who answers: each one is a call of its own for each persona and data set, in this
    order. A voicemail or a call screener answers only a phone call of an outbound agent."""

    @field_validator("persona_ids", "data_set_ids", "answered_by")
    @classmethod
    def each_once[T](cls, items: list[T] | None, info: ValidationInfo) -> list[T] | None:
        kind = {"persona_ids": "persona", "data_set_ids": "data set"}.get(
            info.field_name or "", "answer"
        )
        return listed_once(items, kind)


def each_scenario_once(scenarios: list[RunScenario]) -> list[RunScenario]:
    ids = [scenario.scenario_id for scenario in scenarios]
    repeated = [scenario_id for scenario_id, n in Counter(ids).items() if n > 1]
    if repeated:
        raise ValueError(f"scenario {repeated[0]} is listed more than once")
    return scenarios


ScenarioList = Annotated[list[RunScenario], Field(min_length=1), AfterValidator(each_scenario_once)]
"""In the order the conversations of each repeat start."""


class RunSettings(BaseModel):
    """What a run does with its scenarios, apart from which scenarios: a suite entry keeps the
    same settings. Limits that an operator sets, such as the most repeats, are checked where the
    settings are known."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repeats: int = Field(default=1, ge=1)
    max_duration_s: int | None = Field(default=None, ge=10, le=1800)
    """None takes the operator's default."""
    max_turns: int | None = Field(default=None, ge=1, le=100)
    """How many agent turns the caller answers before it says goodbye; None takes the
    operator's default."""
    max_parallel: int | None = Field(default=None, ge=1)
    start_interval_s: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=0)
    """How many times a conversation that ends with an error is tried again; None takes 1, or
    the operator's limit when that is lower."""


class RunCreate(RunSettings):
    agent_id: uuid.UUID
    transport: Transport | None = None
    """How the conversations reach the agent; None takes the agent's only connection."""
    scenarios: ScenarioList
    name: RunName | None = None

    def request_hash(self) -> str:
        """The same for the same request, so a repeated request can be told from another request
        with the same idempotency key. It covers the request before the operator's defaults,
        which can change between the two."""
        body = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()


class RunStatus(StrEnum):
    QUEUED = "queued"
    """Conversations wait, and none has started."""
    RUNNING = "running"
    CANCELLING = "cancelling"
    """Cancelled while calls are still ending."""
    DONE = "done"
    CANCELLED = "cancelled"


def run_status(*, cancelled: bool, active: bool, started: bool) -> RunStatus:
    """A run's status comes from its conversations each time it is read: whether any is still
    active, and whether any has started."""
    if cancelled:
        return RunStatus.CANCELLING if active else RunStatus.CANCELLED
    if not active:
        return RunStatus.DONE
    return RunStatus.RUNNING if started else RunStatus.QUEUED


class WaitingReason(StrEnum):
    """Why queued conversations of a run have not started. Only the run's own limits are
    named; anything else is a worker or a number."""

    MAX_PARALLEL = "max_parallel"
    START_INTERVAL = "start_interval"
    """A call of the run started less than its start interval ago."""
    WORKER_OR_NUMBER = "worker_or_number"


def waiting_reason(*, queued: bool, full: bool, waiting: bool) -> WaitingReason | None:
    if not queued:
        return None
    if full:
        return WaitingReason.MAX_PARALLEL
    if waiting:
        return WaitingReason.START_INTERVAL
    return WaitingReason.WORKER_OR_NUMBER


class RunProgress(BaseModel):
    """What a run's conversations say about it, counted each time the run is read. The counts,
    end reasons and talk time take only the latest attempt of each repeat of each
    scenario."""

    model_config = ConfigDict(frozen=True)

    status: RunStatus
    cancelled_at: datetime | None
    counts: dict[OutcomeGroup, int]
    end_reasons: dict[EndReason, int]
    answered_by: dict[AnsweredBy, int]
    """Who answered the counted conversations."""
    retries: int
    """How many retries the run made."""
    median_talk_ms: int | None
    waiting_reason: WaitingReason | None
    started_at: datetime | None
    ended_at: datetime | None
