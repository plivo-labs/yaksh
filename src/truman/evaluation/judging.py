"""Asking a judge model about one item: code checks on the answer, one re-ask that names what
was wrong, and a record of every answer."""

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from truman.domain.evaluations import DecidedBy, ItemRole, Outcome, UnsureKind
from truman.domain.language_models import JsonModel, ModelAnswer, ModelCallError
from truman.evaluation.evidence import EVIDENCE_VIEW_VERSION

CODE_CHECKS_VERSION = 1

type Check = Callable[[dict[str, Any]], tuple[list[str], list[str]]]
"""An answer's problems: hard ones always need a new answer, soft ones get one question."""


def prompt(name: str) -> str:
    return resources.files("truman.evaluation.prompts").joinpath(f"{name}.md").read_text()


def sha256(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


@dataclass(frozen=True)
class JudgeSpec:
    """A judge as code defines it; with the model and its settings, it is a judge version."""

    name: str
    system: str
    schema: dict[str, Any]

    def version(self, provider: str, model: str, settings: dict[str, Any]) -> dict[str, Any]:
        """The judge version's fields; its content hash names it."""
        fields = {
            "judge": self.name,
            "provider": provider,
            "model": model,
            "settings": settings,
            "prompt_sha256": sha256(self.system),
            "schema_sha256": sha256(json.dumps(self.schema, sort_keys=True)),
            "evidence_view_version": EVIDENCE_VIEW_VERSION,
            "code_checks_version": CODE_CHECKS_VERSION,
        }
        return fields | {"content_sha256": sha256(json.dumps(fields, sort_keys=True))}


@dataclass(frozen=True)
class Attempt:
    """One answer the model gave, or the failure in its place."""

    request_sha256: str
    model_returned: str | None
    output: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    error: str | None


@dataclass(frozen=True)
class ItemResult:
    key: str
    subject: str
    judge: str | None
    """The judge spec's name; None for an item code decided alone."""
    decided_by: DecidedBy
    role: ItemRole
    outcome: Outcome
    unsure_kind: UnsureKind | None = None
    answer: dict[str, Any] | None = None
    error_reason: str | None = None
    re_asks: int = 0
    attempts: list[Attempt] = field(default_factory=list)


class JudgeUnavailable(Exception):
    """The judge model failed in a way that can pass later, such as a timeout or a rate limit:
    the evaluation is tried again after a wait."""


@dataclass(frozen=True)
class Answered:
    answer: dict[str, Any] | None
    attempts: list[Attempt]
    re_asks: int
    error: str | None


WAITS_S = (10.0, 30.0, 60.0)
"""Waits before asking again after a temporary failure, beyond the client's own quick retries.
The lease's heartbeat goes on meanwhile, so one item waits instead of the whole evaluation
going back to the queue and asking every item again."""


async def ask(
    model: JsonModel,
    spec: JudgeSpec,
    user: str,
    check: Check,
    *,
    slots: asyncio.Semaphore,
    retry_later: bool,
    patient: bool = True,
) -> Answered:
    """The model's answer once it passes the code checks. An answer with problems gets one
    re-ask; a second answer with hard problems is invalid evidence."""
    attempts: list[Attempt] = []
    request = user
    for re_asks in (0, 1):
        answered = await answer(
            model, spec, request, attempts, slots=slots, retry_later=retry_later, patient=patient
        )
        if isinstance(answered, str):
            return Answered(None, attempts, re_asks, answered)
        shape = mismatches(spec.schema, answered.data)
        hard, soft = (shape, []) if shape else check(answered.data)
        problems = hard + soft if re_asks == 0 else hard
        if not problems:
            return Answered(answered.data, attempts, re_asks, None)
        if re_asks == 1:
            return Answered(answered.data, attempts, re_asks, "invalid_evidence")
        request = re_ask(user, answered.data, problems)
    raise AssertionError("unreachable")


async def answer(
    model: JsonModel,
    spec: JudgeSpec,
    request: str,
    attempts: list[Attempt],
    *,
    slots: asyncio.Semaphore,
    retry_later: bool,
    patient: bool,
) -> ModelAnswer | str:
    """The model's answer, or why it gave none. A temporary failure is asked again after each
    wait; when the waits run out, it puts the evaluation off with JudgeUnavailable if it can
    be tried again later, else it is the item's error. An impatient ask does not wait."""
    failure: ModelCallError | None = None
    for wait in (*(WAITS_S if patient else ()), None):
        async with slots:
            started = time.monotonic()
            try:
                answered = await model.complete_json(
                    system=spec.system, user=request, name=spec.name, schema=spec.schema
                )
            except ModelCallError as error:
                attempts.append(
                    Attempt(
                        sha256(request), None, None, None, None, elapsed_ms(started), str(error)
                    )
                )
                if not error.temporary:
                    return "judge_failed"
                failure = error
            else:
                attempts.append(
                    Attempt(
                        sha256(request),
                        answered.model,
                        answered.data,
                        answered.input_tokens,
                        answered.output_tokens,
                        elapsed_ms(started),
                        None,
                    )
                )
                return answered
        if wait is not None:
            await asyncio.sleep(wait)
    if retry_later:
        raise JudgeUnavailable(str(failure)) from failure
    return "judge_unavailable"


TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def mismatches(schema: dict[str, Any], value: Any, path: str = "the answer") -> list[str]:
    """Where an answer does not have the shape its schema asks for. A provider in strict mode
    never sends such an answer; one that does not enforce the schema can."""
    if "anyOf" in schema:
        if any(not mismatches(option, value, path) for option in schema["anyOf"]):
            return []
        return [f"{path} has the wrong type."]
    kind = schema["type"]
    if not isinstance(value, TYPES[kind]) or (kind == "integer" and isinstance(value, bool)):
        return [f"{path} must be of type {kind}."]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path} must be one of {', '.join(schema['enum'])}."]
    if kind == "object":
        problems = [f"{path} has no {key}." for key in schema["required"] if key not in value]
        for key, inner in schema["properties"].items():
            if key in value:
                problems += mismatches(inner, value[key], f"{path}.{key}")
        return problems
    if kind == "array":
        return [
            problem
            for index, item in enumerate(value)
            for problem in mismatches(schema["items"], item, f"{path}[{index}]")
        ]
    return []


def re_ask(user: str, answer: dict[str, Any], problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return (
        f"{user}\n\nYOUR EARLIER ANSWER\n{json.dumps(answer)}\n\n"
        f"PROBLEMS WITH IT\n{listed}\n\nAnswer again and fix these problems."
    )


def elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
