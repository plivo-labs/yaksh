"""The HTTP request that makes an outbound agent place its call, and its placeholders.

A placeholder is `{{kind.name}}` inside a header value or a JSON string value of the body:
`{{truman.number}}`, `{{truman.conversation_id}}`, `{{agent_data.<fact name>}}` and
`{{env.TRUMAN_TRIGGER_<NAME>}}`. The URL and JSON keys take none.
"""

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator

from truman.domain.numbers import E164
from truman.domain.scenarios import Fact, normalized

SEND_TIMEOUT_S = 15
"""How long Truman waits for the trigger's response; the call may arrive before it ends."""
PLACEHOLDER = re.compile(r"\{\{([^{}]*)\}\}")
TRUMAN_VALUES = frozenset({"truman.number", "truman.conversation_id"})
ENV_NAME = re.compile(r"TRUMAN_TRIGGER_[A-Z0-9_]+")
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
RESERVED_HEADERS = frozenset({"content-type", "content-length", "host"})

HeaderValue = Annotated[str, StringConstraints(max_length=2000)]


def placeholders(text: str) -> list[str]:
    """The placeholders in a template string, each checked. Braces that do not form a
    placeholder are an error, so a typo never reaches the agent's system as literal text."""
    found = [match.strip() for match in PLACEHOLDER.findall(text)]
    rest = PLACEHOLDER.sub("", text)
    if "{{" in rest or "}}" in rest:
        raise ValueError(f"unmatched braces in {text!r}")
    for name in found:
        check_placeholder(name)
    return found


def check_placeholder(name: str) -> None:
    kind, _, rest = name.partition(".")
    if name in TRUMAN_VALUES:
        return
    if kind == "agent_data" and rest.strip():
        return
    if kind == "env" and ENV_NAME.fullmatch(rest):
        return
    if kind == "env":
        raise ValueError(f"{{{{{name}}}}}: only environment variables named TRUMAN_TRIGGER_*")
    raise ValueError(f"unknown placeholder {{{{{name}}}}}")


def template_strings(value: Any) -> Iterator[str]:
    """Every string value in a JSON body; object keys are checked to hold no placeholder."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if "{{" in key or "}}" in key:
                raise ValueError(f"placeholders are not allowed in JSON keys: {key!r}")
            yield from template_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from template_strings(item)


class Header(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    value: HeaderValue

    @field_validator("name")
    @classmethod
    def usable_name(cls, name: str) -> str:
        if not HEADER_NAME.fullmatch(name):
            raise ValueError(f"not a valid header name: {name!r}")
        lower = name.lower()
        if lower in RESERVED_HEADERS or lower.startswith("x-truman-"):
            raise ValueError(f"Truman sets the {name} header itself")
        return name

    @field_validator("value")
    @classmethod
    def usable_value(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("a header value cannot contain a line break")
        placeholders(value)
        return value


class Trigger(BaseModel):
    """A POST with a JSON body, sent once for each conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: HttpUrl
    headers: list[Header] = Field(default_factory=list, max_length=30)
    body: dict[str, Any]

    @field_validator("url", mode="before")
    @classmethod
    def no_placeholders(cls, url: object) -> object:
        if isinstance(url, str) and ("{{" in url or "}}" in url):
            raise ValueError("placeholders are not allowed in the URL")
        return url

    @field_validator("headers")
    @classmethod
    def distinct_headers(cls, headers: list[Header]) -> list[Header]:
        names = [header.name.lower() for header in headers]
        if len(set(names)) != len(names):
            raise ValueError("header names must be unique")
        return headers

    @field_validator("body")
    @classmethod
    def valid_placeholders(cls, body: dict[str, Any]) -> dict[str, Any]:
        for text in template_strings(body):
            placeholders(text)
        return body


class OutboundConfig(BaseModel):
    """How an outbound agent is made to call Truman, and how its call is recognized."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger: Trigger
    calling_numbers: list[E164] = Field(default_factory=list, max_length=50)
    dial_window_s: int = Field(default=120, ge=10, le=600)

    @field_validator("calling_numbers")
    @classmethod
    def distinct_numbers(cls, numbers: list[str]) -> list[str]:
        if len(set(numbers)) != len(numbers):
            raise ValueError("calling numbers must be unique")
        return numbers


class RenderError(ValueError):
    """The trigger cannot be sent: a placeholder has no value, or a value breaks a header."""


@dataclass(frozen=True)
class RenderedTrigger:
    url: str
    headers: dict[str, str]
    body: bytes
    secrets: tuple[str, ...]
    """The environment values the request carries, to mask wherever it is stored."""


def render(
    trigger: Trigger,
    *,
    number: str,
    conversation_id: str,
    agent_data: list[Fact],
    env: Mapping[str, str],
) -> RenderedTrigger:
    """The request with every placeholder replaced. Values go inside JSON strings of the parsed
    body, so no value can change the JSON's shape."""
    facts = {normalized(fact.name): fact.value for fact in agent_data}
    secrets: list[str] = []

    def value_of(name: str) -> str:
        kind, _, rest = name.partition(".")
        if name == "truman.number":
            return number
        if name == "truman.conversation_id":
            return conversation_id
        if kind == "agent_data":
            if normalized(rest) not in facts:
                raise RenderError(f"the scenario has no agent data named {rest!r}")
            return facts[normalized(rest)]
        if rest not in env:
            raise RenderError(f"the environment variable {rest} is not set")
        secrets.append(env[rest])
        return env[rest]

    def fill(value: Any) -> Any:
        if isinstance(value, str):
            return PLACEHOLDER.sub(lambda match: value_of(match.group(1).strip()), value)
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return value

    headers = {header.name: fill(header.value) for header in trigger.headers}
    for name, value in headers.items():
        if "\r" in value or "\n" in value:
            raise RenderError(f"a placeholder puts a line break into the {name} header")
    body = json.dumps(fill(trigger.body)).encode()
    return RenderedTrigger(str(trigger.url), headers, body, tuple(secrets))


def agent_data_names(trigger: Trigger) -> set[str]:
    """The agent data a scenario must provide for this trigger, by normalized fact name."""
    texts = [header.value for header in trigger.headers] + list(template_strings(trigger.body))
    return {
        normalized(name.partition(".")[2])
        for text in texts
        for name in placeholders(text)
        if name.startswith("agent_data.")
    }
