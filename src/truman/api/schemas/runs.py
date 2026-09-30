import uuid
from datetime import datetime

from pydantic import BaseModel

from truman.domain.conversations import EndReason, OutcomeGroup
from truman.domain.runs import RunStatus, WaitingReason


class CallerClaims(BaseModel):
    """What the callers of the latest attempts said when they hung up: claims, not verdicts."""

    reached: int
    not_reached: int


class RunSummary(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_version: int
    agent_name: str
    name: str | None
    repeats: int
    max_duration_s: int
    max_parallel: int | None
    start_interval_s: int | None
    retries: int
    status: RunStatus
    counts: dict[OutcomeGroup, int]
    """The latest attempt of each repeat of each scenario, by outcome group."""
    end_reasons: dict[EndReason, int]
    retried: int
    caller_claims: CallerClaims
    median_talk_ms: int | None
    waiting_reason: WaitingReason | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    cancelled_at: datetime | None


class RunRead(RunSummary):
    scenario_ids: list[uuid.UUID]
    """In the order the conversations of each repeat start."""
