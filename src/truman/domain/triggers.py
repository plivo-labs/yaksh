"""The HTTP request that makes an outbound agent place its call, and its placeholders.

A placeholder is `{{kind.name}}` inside a header value or a JSON string value of the body:
`{{truman.number}}`, `{{truman.conversation_id}}`, `{{agent_data.<fact name>}}` and
`{{env.TRUMAN_TRIGGER_<NAME>}}`. The URL and JSON keys take none.
"""

import re
from collections.abc import Iterator
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator

from truman.domain.numbers import E164

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
