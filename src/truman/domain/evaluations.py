"""Evaluations: measuring and judging a saved conversation, and what they produce."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class MetricKey(StrEnum):
    SPEECH = "speech"
    RESPONSE_TIME = "response_time"


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
