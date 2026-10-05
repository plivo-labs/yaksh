"""Evaluations: measuring and judging a saved conversation, and what they produce."""

import math
import uuid
from datetime import datetime
from enum import StrEnum
from statistics import NormalDist
from typing import Any

from pydantic import BaseModel, ConfigDict

from truman.domain.background_noise import BackgroundNoise
from truman.domain.scenarios import Category


class MetricKey(StrEnum):
    USAGE = "usage"
    CAPTURE_FAULTS = "capture_faults"
    AGENT_REPETITION = "agent_repetition"
    SPEECH = "speech"
    RESPONSE_TIME = "response_time"
    TURN_TAKING = "turn_taking"
    SPEAKING = "speaking"


class Outcome(StrEnum):
    """An item's result: a judge's verdict, or what stopped one."""

    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    UNSURE = "unsure"
    BLOCKED = "blocked"
    """The caller, the scenario or the test's limits broke the test for this item."""
    ERROR = "error"
    """The judge failed; the item has no verdict."""
    PENDING = "pending"
    """Labels disagree, so no effective outcome yet."""


class UnsureKind(StrEnum):
    HIDDEN_ACTION = "hidden_action"
    """Deciding needs a tool call or a backend state the call cannot show; counts as not
    applicable."""
    NOT_CONFIRMED_PLAYED = "not_confirmed_played"
    UNCLEAR = "unclear"


class DecidedBy(StrEnum):
    CODE = "code"
    JEV = "jev"
    LLM = "llm"


class ItemRole(StrEnum):
    DECIDING = "deciding"
    """Counts in the conversation verdict."""
    REPORTING = "reporting"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_SCORED = "not_scored"


class LabelAnswer(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    CANNOT_TELL = "cannot_tell"
    BLOCKED = "blocked"


class LabelReason(StrEnum):
    """Why the labeler answered so. No reason names a cause inside the agent."""

    AGENT_ERROR = "agent_error"
    APPLICABILITY = "applicability"
    TRANSCRIPT_ERROR = "transcript_error"
    SPOKEN_FORM = "spoken_form"
    DATE_OR_TIME = "date_or_time"
    READ_BACK = "read_back"
    WINDOW_OR_ORDER = "window_or_order"
    EXACT_VALUE = "exact_value"
    HIDDEN_ACTION = "hidden_action"
    EVIDENCE_MISREAD = "evidence_misread"
    CRITERION_AMBIGUOUS = "criterion_ambiguous"
    CALLER_ERROR = "caller_error"
    SCENARIO_ERROR = "scenario_error"
    TEST_SETTINGS_ERROR = "test_settings_error"
    LINE_OR_AUDIO = "line_or_audio"
    OTHER = "other"
    """Needs a note."""


class Lane(StrEnum):
    AUDIT = "audit"
    """The random sample: its blind labels measure the judges."""
    AD_HOC = "ad_hoc"
    """Items people picked: their labels change verdicts but never measure a judge."""


class EvaluationState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    """Every attempt failed; it is not tried again."""


class Metric(BaseModel):
    """One metric's value and the flags it raised."""

    model_config = ConfigDict(frozen=True)

    value: dict[str, Any]
    flags: list[str] = []


Z95 = NormalDist().inv_cdf(0.975)


class Share(BaseModel):
    """How many of a total, with the 95% Wilson interval of the rate: few calls give a wide
    interval."""

    model_config = ConfigDict(frozen=True)

    count: int
    total: int
    low: float | None
    high: float | None

    @classmethod
    def of(cls, count: int, total: int) -> Share:
        if not total:
            return cls(count=count, total=total, low=None, high=None)
        rate, z2 = count / total, Z95 * Z95
        centre = (rate + z2 / (2 * total)) / (1 + z2 / total)
        half = (
            Z95 * math.sqrt(rate * (1 - rate) / total + z2 / (4 * total * total)) / (1 + z2 / total)
        )
        return cls(
            count=count,
            total=total,
            low=round(max(0.0, centre - half), 3),
            high=round(min(1.0, centre + half), 3),
        )


class RunNumbers(BaseModel):
    """What the evaluations found over some of a run's conversations."""

    model_config = ConfigDict(frozen=True)

    conversations: int
    evaluated: int
    pending: int
    """Not evaluated yet: the call or its evaluation is still to come."""
    failed: int
    """Every attempt to evaluate failed."""
    connected: Share
    """Calls whose audio started, of the calls that connected or did not connect. Truman's own
    errors before a call connected are left out and counted on their own."""
    errors_before_connect: int
    response_p50_ms: int | None
    response_p90_ms: int | None
    """Nearest rank over the response times of all the calls, pooled."""
    unanswered: Share
    """Calls with a reply the agent did not answer, of the calls with turn taking. Each share
    counts calls, as one call's replies are not independent of each other."""
    talked_over: Share
    """Calls where the agent talked over a reply, of the calls with turn taking."""
    long_wait: Share
    """Calls with a wait of 5 s or more, of the calls with turn taking."""
    dead_air: Share
    """Calls with a wait of 10 s or more, of the calls with turn taking."""
    flags: dict[str, int]
    """How many calls raised each flag, over all metrics."""


class CategoryNumbers(BaseModel):
    category: Category
    """The scenario's category as it is now; a category is not versioned."""
    numbers: RunNumbers


class NoiseNumbers(BaseModel):
    noise: BackgroundNoise
    """The background noise the calls played."""
    numbers: RunNumbers


class CallVerdict(BaseModel):
    conversation_id: uuid.UUID
    repeat: int
    verdict: Verdict | None
    """The scenario verdict after labels; None when the evaluation failed."""


class ScenarioVerdicts(BaseModel):
    scenario_id: uuid.UUID
    name: str
    category: Category
    calls: list[CallVerdict]
    """The scenario's judged calls, in repeat order."""
    passes: int
    scored: int


class CriterionCounts(BaseModel):
    scenario_id: uuid.UUID
    number: int
    text: str
    counts: dict[str, int]
    """By outcome after labels; an unsure item that needs a hidden action counts as
    "not_testable"."""
    rate: float | None
    """Passes over passes and fails."""


class CallerFidelity(BaseModel):
    persona: str
    calls: int
    """Judged calls whose caller check answered."""
    likely: int
    possible: int


class JudgeVersionUsed(BaseModel):
    judge: str
    model: str
    version: str
    """The start of the version's content hash."""
    items: int
    """The run's items this version judged."""


class RunVerdicts(BaseModel):
    """The run's verdict numbers over its judged calls: completed calls that no one stopped,
    whose evaluation gave a verdict or failed."""

    pending: int
    """Calls whose evaluation is queued or running."""
    not_judged: int
    """Calls evaluated with no judge model: they have metrics but no verdict."""
    pass_rate: float | None
    """The mean over scenarios of each one's passes over its scored calls."""
    coverage: float | None
    """Scored calls over judged calls; a failed evaluation counts as unscored. Below 0.95, the
    worst-to-best range is the main number."""
    worst: float | None
    best: float | None
    interval_low: float | None
    interval_high: float | None
    """The "this suite" 95% interval; none below five scenarios."""
    pass_hat_2: float | None
    """The chance that two repeats of a scenario both pass, over the scenarios with two scored
    calls."""
    pass_hat_2_scenarios: int
    scenarios: list[ScenarioVerdicts]
    """In the run's order."""
    inconsistent: list[uuid.UUID]
    """Scenarios that both passed and failed across repeats. No cause is named: repeats mix the
    agent, the caller and the line."""
    criteria: list[CriterionCounts]
    decided_by: dict[DecidedBy, int]
    """The criteria and agent rules that code, Jev or the judge model decided."""
    errors: int
    """The criteria and agent rules that no judge could decide."""
    callers: list[CallerFidelity]
    judge_versions: list[JudgeVersionUsed]


class RunMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall: RunNumbers
    by_category: list[CategoryNumbers]
    by_noise: list[NoiseNumbers]
    verdicts: RunVerdicts


class VersionAgreement(BaseModel):
    judge: str
    model: str
    version: str
    """The start of the version's content hash."""
    items: Share
    """The items this version decided whose first blind audit label agrees with it."""


class JudgeAgreement(BaseModel):
    """How often blind audit labels agree with the machine. A judge version with no such labels
    is not listed: it is not yet measured on your agents."""

    versions: list[VersionAgreement]
    conversations: Share
    """Calls whose criteria all have a blind label, where the scenario verdict of those labels
    agrees with the machine's."""
    labelers: Share
    """Items with blind labels from two labelers, where the first two agree."""
    offered_calls: Share
    """The audit calls the queue offers that have a label on every auditable item: a low share
    means the measure leaves calls out."""


class QueuedReview(BaseModel):
    conversation_id: uuid.UUID
    scenario_name: str
    ended_at: datetime
    items: int
    labeled: int
    """The items this labeler labeled."""
