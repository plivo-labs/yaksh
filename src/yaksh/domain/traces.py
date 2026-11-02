"""What Yaksh keeps of the traces that an agent sends: the spans that a framework reader uses,
with their timing values and link keys, never the call's content. A span with a link key and a
name no reader uses is kept as its key only, so a key on a span of the agent's own still links
its trace."""

import hashlib
import re
import secrets
import string
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span

CONVERSATION_KEY = "yaksh.conversation_id"
NUMBER_KEY = "yaksh.number"
MAX_KEY_CHARS = 64
MAX_SPANS = 20_000
"""Spans in one request; an exporter sends 512 or fewer by default."""
MAX_NS = 2**63 - 1
"""The latest time that the BIGINT columns hold: OTLP times are unsigned."""
MAX_SECONDS = 86_400.0
"""No timing value of a call is longer than a day, and 1e308 s overflows when a reader makes
it ns."""

LIVEKIT_SPANS = frozenset(
    {
        "agent_session",
        "user_turn",
        "eou_wait",
        "eou_detection",
        "agent_turn",
        "llm_node",
        "tts_node",
        "function_tool",
        "agent_speaking",
    }
)
PIPECAT_SPANS = frozenset({"conversation", "turn", "llm", "tts"})
READ_SPANS = LIVEKIT_SPANS | PIPECAT_SPANS


class Kind(StrEnum):
    TEXT = "text"
    SECONDS = "seconds"
    FLAG = "flag"
    COUNT = "count"


TIMING_ATTRIBUTES = {
    "lk.speech_id": Kind.TEXT,
    "lk.generation_id": Kind.TEXT,
    "lk.parent_generation_id": Kind.TEXT,
    "lk.e2e_latency": Kind.SECONDS,
    "lk.end_of_turn_delay": Kind.SECONDS,
    "lk.transcription_delay": Kind.SECONDS,
    "lk.response.ttft": Kind.SECONDS,
    "lk.response.ttfb": Kind.SECONDS,
    "lk.interrupted": Kind.FLAG,
    "lk.eou.source": Kind.TEXT,
    "turn.user_bot_latency_seconds": Kind.SECONDS,
    "turn.number": Kind.COUNT,
    "turn.was_interrupted": Kind.FLAG,
    "metrics.ttfb": Kind.SECONDS,
}
"""The attributes that Yaksh keeps, with the type each must have."""

KIND_NAMES = {
    Kind.TEXT: "a string with no NUL character",
    Kind.SECONDS: f"a number from -{MAX_SECONDS:.0f} to {MAX_SECONDS:.0f}",
    Kind.FLAG: "a boolean",
    Kind.COUNT: "an integer",
}

NUMBER_CHARACTERS = re.compile(r"[\s().-]")
E164_DIGITS = re.compile(r"[1-9]\d{6,14}")


@dataclass(frozen=True)
class KeptSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_ns: int
    end_ns: int
    attributes: dict[str, Any]
    conversation_id: uuid.UUID | None
    number: str | None

    @property
    def keyed(self) -> bool:
        return self.conversation_id is not None or self.number is not None


@dataclass
class Sorted:
    """What one export request brought: the spans to keep, and why others were rejected."""

    kept: list[KeptSpan] = field(default_factory=list)
    rejected: int = 0
    reasons: list[str] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.rejected += 1
        if reason not in self.reasons:
            self.reasons.append(reason)


class RejectedSpan(Exception):
    pass


def span_count(request: ExportTraceServiceRequest) -> int:
    return sum(
        len(scope.spans) for resource in request.resource_spans for scope in resource.scope_spans
    )


def sort_spans(request: ExportTraceServiceRequest, numbers: Collection[str]) -> Sorted:
    """The spans of one export request that Yaksh keeps. numbers are Yaksh's own: a span whose
    number is another is from a call that is not a test, and Yaksh drops it unless it also has
    a conversation ID."""
    found = Sorted()
    for resource in request.resource_spans:
        for scope in resource.scope_spans:
            for span in scope.spans:
                try:
                    kept = keep(span, numbers)
                except RejectedSpan as error:
                    found.reject(str(error))
                    continue
                if kept is not None:
                    found.kept.append(kept)
    return found


def keep(span: Span, numbers: Collection[str]) -> KeptSpan | None:
    """The span as Yaksh keeps it, or None when Yaksh drops it. Raises RejectedSpan for a span
    that breaks the format."""
    values = {attribute.key: attribute.value for attribute in span.attributes}
    conversation_id = link_conversation(values.get(CONVERSATION_KEY))
    number = link_number(values.get(NUMBER_KEY))
    if number is not None and number not in numbers:
        if conversation_id is None:
            return None
        number = None
    read = span.name in READ_SPANS
    if not read and conversation_id is None and number is None:
        return None
    trace_id, span_id = span_ids(span)
    if "\x00" in span.name:
        raise RejectedSpan("a span name has a NUL character")
    if not 0 < span.start_time_unix_nano <= span.end_time_unix_nano <= MAX_NS:
        raise RejectedSpan("a span has a bad start or end time")
    return KeptSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=span.parent_span_id.hex() if any(span.parent_span_id) else None,
        name=span.name,
        start_ns=span.start_time_unix_nano,
        end_ns=span.end_time_unix_nano,
        attributes=timing(values) if read else {},
        conversation_id=conversation_id,
        number=number,
    )


def span_ids(span: Span) -> tuple[str, str]:
    if len(span.trace_id) != 16 or not any(span.trace_id):
        raise RejectedSpan("a span has a bad trace ID")
    if len(span.span_id) != 8 or not any(span.span_id):
        raise RejectedSpan("a span has a bad span ID")
    return span.trace_id.hex(), span.span_id.hex()


def link_key(value: AnyValue | None) -> str | None:
    if value is None:
        return None
    if value.WhichOneof("value") != "string_value" or len(value.string_value) > MAX_KEY_CHARS:
        raise RejectedSpan(f"a link key must be a string of {MAX_KEY_CHARS} characters or fewer")
    return value.string_value.strip() or None


def link_conversation(value: AnyValue | None) -> uuid.UUID | None:
    """An ID that is not a UUID is not a Yaksh call, so it links nothing."""
    key = link_key(value)
    if key is None:
        return None
    try:
        return uuid.UUID(key)
    except ValueError:
        return None


def link_number(value: AnyValue | None) -> str | None:
    key = link_key(value)
    return None if key is None else e164(key)


def e164(number: str) -> str | None:
    """The number as + and digits, as Yaksh stores its own: 14155550101 is +14155550101."""
    digits = NUMBER_CHARACTERS.sub("", number).removeprefix("+")
    return f"+{digits}" if E164_DIGITS.fullmatch(digits) else None


def timing(values: dict[str, AnyValue]) -> dict[str, Any]:
    kept = {}
    for key, kind in TIMING_ATTRIBUTES.items():
        value = values.get(key)
        if value is not None:
            kept[key] = typed(key, kind, value)
    return kept


def typed(key: str, kind: Kind, value: AnyValue) -> str | float | bool | int:
    match kind, value.WhichOneof("value"):
        case Kind.TEXT, "string_value" if "\x00" not in value.string_value:
            return value.string_value
        case Kind.SECONDS, "double_value" if abs(value.double_value) <= MAX_SECONDS:
            return value.double_value
        case Kind.SECONDS, "int_value" if abs(value.int_value) <= MAX_SECONDS:
            return float(value.int_value)
        case Kind.FLAG, "bool_value":
            return value.bool_value
        case Kind.COUNT, "int_value":
            return value.int_value
    raise RejectedSpan(f"{key} must be {KIND_NAMES[kind]}")


TOKEN_PREFIX = "yks_"
TOKEN_ALPHABET = string.ascii_letters + string.digits


def new_token() -> str:
    """yks_ and 40 random characters; the prefix lets secret scanners find a token that
    leaked."""
    return TOKEN_PREFIX + "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(40))


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
