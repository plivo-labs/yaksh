"""Runs: conversations of several scenarios started together against one agent, each scenario
repeated."""

import hashlib
import json
import uuid
from collections import Counter
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from truman.domain.scenarios import MAX_BULK

RunName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class RunCreate(BaseModel):
    """Limits that an operator sets, such as the most repeats, are checked where the settings
    are known."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: uuid.UUID
    scenario_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK)
    """In the order the conversations of each repeat start."""
    repeats: int = Field(default=1, ge=1)
    max_duration_s: int | None = Field(default=None, ge=10, le=1800)
    max_parallel: int | None = Field(default=None, ge=1)
    start_interval_s: int | None = Field(default=None, ge=1)
    retries: int = Field(default=1, ge=0)
    name: RunName | None = None

    @field_validator("scenario_ids")
    @classmethod
    def each_scenario_once(cls, ids: list[uuid.UUID]) -> list[uuid.UUID]:
        repeated = [scenario_id for scenario_id, n in Counter(ids).items() if n > 1]
        if repeated:
            raise ValueError(f"scenario {repeated[0]} is listed more than once")
        return ids

    def request_hash(self) -> str:
        """The same for the same request with its defaults applied, so a repeated request can
        be told from another request with the same idempotency key."""
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
