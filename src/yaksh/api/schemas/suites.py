import uuid
from datetime import datetime

from pydantic import BaseModel

from yaksh.api.schemas.runs import RunSummary
from yaksh.domain.evaluations import GateNumbers
from yaksh.domain.suites import RunResult, SuiteEntry


class SuiteEntryRead(SuiteEntry):
    position: int
    agent_name: str
    scenario_count: int
    """How many scenarios a start runs now; for all scenarios, the agent's live ones."""
    calls: int
    """The conversations each suite run starts for the entry: personas times data sets times
    answers times repeats, for each scenario."""
    problems: list[str]
    """Why a start would refuse the entry now, such as a deleted scenario. A save keeps them, so
    broken entries can be fixed one at a time."""


class SuiteRunSummary(BaseModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    suite_name: str
    required_pass_percent: int
    """The suite's value when the suite run started."""
    result: RunResult
    created_at: datetime
    ended_at: datetime | None
    """When its last run ended; None while one is at work."""
    cancelled_at: datetime | None
    run_count: int
    passed_run_count: int
    conversation_count: int
    """The latest attempt of each conversation of its runs."""


class SuiteSummary(BaseModel):
    id: uuid.UUID
    name: str
    required_pass_percent: int
    revision: int
    """Send it back with a change: a change of an older read is refused."""
    created_at: datetime
    updated_at: datetime
    agent_names: list[str]
    """The agents of the entries, each once, in entry order."""
    calls: int
    """The conversations one suite run starts."""
    last_run: SuiteRunSummary | None


class SuiteRead(SuiteSummary):
    entries: list[SuiteEntryRead]


class SuiteRunPart(BaseModel):
    """One run of a suite run, with its result against the suite run's pass rate."""

    run: RunSummary
    result: RunResult
    numbers: GateNumbers


class SuiteRunRead(SuiteRunSummary):
    runs: list[SuiteRunPart]
    """In entry order."""
