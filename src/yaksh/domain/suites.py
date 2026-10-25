"""Test suites: saved lists of runs that start together, and how a suite run gets its result
(docs/decisions/0034)."""

import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from yaksh.domain.agents import Transport
from yaksh.domain.answering import AnsweredBy
from yaksh.domain.evaluations import FULL_COVERAGE, GateNumbers
from yaksh.domain.runs import (
    RunCreate,
    RunName,
    RunScenario,
    RunSettings,
    RunStatus,
    ScenarioList,
    listed_once,
)

SuiteName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
PassPercent = Annotated[int, Field(ge=1, le=100)]
"""A whole percent, as the console shows it."""
MAX_ENTRIES = 100
"""Each run has its own most conversations, so this also bounds a suite run."""
MARGIN = 1e-9
"""A pass rate is a float mean; a rate equal to the required percent passes."""


class AllScenarios(BaseModel):
    """Every live scenario of the agent at each start, each with its own persona and all its
    data sets, answered by each of these answers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answered_by: list[AnsweredBy] = Field(default=[AnsweredBy.CALLER], min_length=1)

    @field_validator("answered_by")
    @classmethod
    def each_once(cls, items: list[AnsweredBy]) -> list[AnsweredBy]:
        listed_once(items, "answer")
        return items


class SuiteEntry(RunSettings):
    """One run of a suite run: an agent over one connection, its scenarios and settings."""

    agent_id: uuid.UUID
    transport: Transport
    scenarios: ScenarioList | AllScenarios
    """The scenarios with their personas, data sets and answers, or all of them. A chosen
    scenario without personas is saved with its own persona."""

    def run_create(self, scenarios: list[RunScenario], name: RunName) -> RunCreate:
        return RunCreate(
            **self.model_dump(include=set(RunSettings.model_fields)),
            agent_id=self.agent_id,
            transport=self.transport,
            scenarios=scenarios,
            name=name,
        )


class SuiteCreate(BaseModel):
    """A new suite has no entries; the suite page adds them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: SuiteName
    required_pass_percent: PassPercent = 80


class SuiteUpdate(BaseModel):
    """A partial change. The entries, when given, replace the suite's entries as a whole."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int
    """The suite's revision that the client read; another one is refused, so two editors cannot
    drop each other's changes."""
    name: SuiteName | None = None
    required_pass_percent: PassPercent | None = None
    entries: Annotated[list[SuiteEntry], Field(max_length=MAX_ENTRIES)] | None = None


class RunResult(StrEnum):
    RUNNING = "running"
    JUDGING = "judging"
    PASSED = "passed"
    FAILED = "failed"
    NOT_DECIDED = "not_decided"
    """Calls that are not scored decide the result: the run reaches the required rate if they
    passed, and misses it if they failed."""
    CANCELLED = "cancelled"


def reaches(rate: float, percent: int) -> bool:
    return rate * 100 + MARGIN >= percent


def run_result(status: RunStatus, gate: GateNumbers, required_percent: int) -> RunResult:
    """The first rule that applies. A cancelled run waits for the judges of the calls that
    completed, so a result never stops changing before its judges are done."""
    if status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLING):
        return RunResult.RUNNING
    if gate.pending:
        return RunResult.JUDGING
    if status is RunStatus.CANCELLED:
        return RunResult.CANCELLED
    if gate.unplayed_failed or gate.unplayed_not_scored:
        return RunResult.FAILED
    if gate.passed + gate.failed + gate.not_scored == 0:
        return RunResult.PASSED
    if gate.coverage is not None and gate.coverage >= FULL_COVERAGE:
        assert gate.pass_rate is not None
        return RunResult.PASSED if reaches(gate.pass_rate, required_percent) else RunResult.FAILED
    assert gate.worst is not None and gate.best is not None
    if reaches(gate.worst, required_percent):
        return RunResult.PASSED
    if not reaches(gate.best, required_percent):
        return RunResult.FAILED
    return RunResult.NOT_DECIDED


SUITE_ORDER = (
    RunResult.RUNNING,
    RunResult.JUDGING,
    RunResult.FAILED,
    RunResult.CANCELLED,
    RunResult.NOT_DECIDED,
)


def suite_result(results: Sequence[RunResult]) -> RunResult:
    """The first result in this order that a run has, else passed: a run still at work keeps
    the suite run waiting, and a failure comes before a cancel, because it tells something about
    the agent and a cancel tells only about the test."""
    return next((result for result in SUITE_ORDER if result in results), RunResult.PASSED)


class SuiteRunLink(BaseModel):
    """The suite run that started a run."""

    id: uuid.UUID
    suite_id: uuid.UUID
    suite_name: str
    position: int
