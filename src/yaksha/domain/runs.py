"""Runs: conversations of several scenarios started together against one agent, each scenario
repeated."""

import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from yaksha.domain.conversations import EndReason, OutcomeGroup

RunName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class RunScenario(BaseModel):
    """A scenario of a run and the personas that call it. None is the scenario's own persona."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: uuid.UUID
    persona_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    """In the order their conversations start."""

    @field_validator("persona_ids")
    @classmethod
    def each_persona_once(cls, ids: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        repeated = [persona_id for persona_id, n in Counter(ids or []).items() if n > 1]
        if repeated:
            raise ValueError(f"persona {repeated[0]} is listed more than once")
        return ids

    @property
    def call_count(self) -> int:
        return len(self.persona_ids) if self.persona_ids else 1


class RunCreate(BaseModel):
    """Limits that an operator sets, such as the most repeats, are checked where the settings
    are known."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: uuid.UUID
    scenarios: list[RunScenario] = Field(min_length=1)
    """In the order the conversations of each repeat start."""
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
    name: RunName | None = None

    @field_validator("scenarios")
    @classmethod
    def each_scenario_once(cls, scenarios: list[RunScenario]) -> list[RunScenario]:
        ids = [scenario.scenario_id for scenario in scenarios]
        repeated = [scenario_id for scenario_id, n in Counter(ids).items() if n > 1]
        if repeated:
            raise ValueError(f"scenario {repeated[0]} is listed more than once")
        return scenarios

    @property
    def calls_per_repeat(self) -> int:
        return sum(scenario.call_count for scenario in self.scenarios)

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
    retries: int
    """How many retries the run made."""
    median_talk_ms: int | None
    waiting_reason: WaitingReason | None
    started_at: datetime | None
    ended_at: datetime | None
