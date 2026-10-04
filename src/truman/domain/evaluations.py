"""Evaluations: measuring and judging a saved conversation, and what they produce."""

import math
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


class RunMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall: RunNumbers
    by_category: list[CategoryNumbers]
    by_noise: list[NoiseNumbers]
