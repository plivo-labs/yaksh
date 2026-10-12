"""The HTTP request that makes an outbound agent place its call, and its placeholders.

A placeholder is `{{kind.name}}` inside a header value, a query parameter value or a JSON string
value of the body: `{{yaksh.number}}`, `{{yaksh.conversation_id}}`,
`{{agent_data.<fact name>}}` and `{{secrets.<NAME>}}`, a trigger secret from Settings. The URL,
query parameter names and JSON keys take none.
"""

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any
from urllib.parse import quote_plus, urlencode, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)
from yarl import URL

from yaksh.domain.errors import ValidationError
from yaksh.domain.numbers import E164
from yaksh.domain.scenarios import Fact, ScenarioConfig, normalized
from yaksh.domain.settings import TRIGGER_SECRET_NAME

SEND_TIMEOUT_S = 15
"""How long Yaksh waits for the trigger's response; the call may arrive before it ends."""
PLACEHOLDER = re.compile(r"\{\{([^{}]*)\}\}")
YAKSH_VALUES = frozenset({"yaksh.number", "yaksh.conversation_id"})
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
    if name in YAKSH_VALUES:
        return
    if kind == "agent_data" and rest.strip():
        return
    if kind == "secrets" and TRIGGER_SECRET_NAME.fullmatch(rest):
        return
    if kind == "secrets":
        raise ValueError(
            f"{{{{{name}}}}}: a secret name uses capital letters, digits and _, "
            "starting with a letter"
        )
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
        if lower in RESERVED_HEADERS or lower.startswith("x-yaksh-"):
            raise ValueError(f"Yaksh sets the {name} header itself")
        return name

    @field_validator("value")
    @classmethod
    def usable_value(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("a header value cannot contain a line break")
        placeholders(value)
        return value


class QueryParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    value: HeaderValue

    @field_validator("name")
    @classmethod
    def no_placeholders(cls, name: str) -> str:
        if "{{" in name or "}}" in name:
            raise ValueError(f"placeholders are not allowed in query parameter names: {name!r}")
        return name

    @field_validator("value")
    @classmethod
    def valid_placeholders(cls, value: str) -> str:
        placeholders(value)
        return value


class TriggerMethod(StrEnum):
    POST = "POST"
    GET = "GET"


class Trigger(BaseModel):
    """The request sent once for each conversation: a POST carries its values in a JSON body,
    a GET in query parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: TriggerMethod = TriggerMethod.POST
    url: HttpUrl
    headers: list[Header] = Field(default_factory=list, max_length=30)
    query: list[QueryParameter] = Field(default_factory=list, max_length=30)
    body: dict[str, Any] | None = None

    @field_validator("url", mode="before")
    @classmethod
    def no_placeholders(cls, url: object) -> object:
        if isinstance(url, str) and ("{{" in url or "}}" in url):
            raise ValueError("placeholders are not allowed in the URL")
        if isinstance(url, str) and "#" in url:
            raise ValueError("the URL cannot have a fragment (#); it is never sent")
        return url

    @field_validator("url")
    @classmethod
    def sent_as_written(cls, url: HttpUrl) -> HttpUrl:
        # The HTTP client moves these out of the URL it sends, so a signed URL would not match.
        if url.username or url.password:
            raise ValueError("the URL cannot hold a user name or password; send them in a header")
        if (url.host or "").endswith("."):
            raise ValueError("the URL's host cannot end with a dot")
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
    def valid_placeholders(cls, body: dict[str, Any] | None) -> dict[str, Any] | None:
        for text in template_strings(body):
            placeholders(text)
        return body

    @model_validator(mode="after")
    def fits_method(self) -> Trigger:
        if self.method is TriggerMethod.POST:
            if self.body is None:
                raise ValueError("a POST trigger needs a JSON body")
            if self.query:
                raise ValueError(
                    "a POST trigger sends its values in the body; put fixed query values in the URL"
                )
        elif self.body is not None:
            raise ValueError("a GET trigger has no body; send its values as query parameters")
        return self

    def template_texts(self) -> list[str]:
        """Every string that may hold placeholders."""
        return (
            [header.value for header in self.headers]
            + [parameter.value for parameter in self.query]
            + list(template_strings(self.body))
        )


class OutboundConfig(BaseModel):
    """How an outbound agent is made to call Yaksh, and how its call is recognized."""

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
    method: TriggerMethod
    url: str
    """With the query parameters, percent-encoded; it is sent as it is."""
    headers: dict[str, str]
    body: bytes
    """Empty for a GET."""
    secrets: tuple[str, ...]
    """The secret values the request carries, to mask wherever it is stored."""


def render(
    trigger: Trigger,
    *,
    number: str,
    conversation_id: str,
    agent_data: list[Fact],
    secrets: Mapping[str, str],
) -> RenderedTrigger:
    """The request with every placeholder replaced. Values go inside JSON strings of the parsed
    body, or are percent-encoded into query values, so no value can change the request's shape."""
    facts = {normalized(fact.name): fact.value for fact in agent_data}
    carried: list[str] = []

    def value_of(name: str) -> str:
        kind, _, rest = name.partition(".")
        if name == "yaksh.number":
            return number
        if name == "yaksh.conversation_id":
            return conversation_id
        if kind == "agent_data":
            if normalized(rest) not in facts:
                raise RenderError(f"the scenario has no agent data named {rest!r}")
            return facts[normalized(rest)]
        if rest not in secrets:
            raise RenderError(f"the trigger secret {rest} is not set; add it in Settings")
        carried.append(secrets[rest])
        return secrets[rest]

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
    url = str(trigger.url)
    if trigger.query:
        query = urlencode([(parameter.name, fill(parameter.value)) for parameter in trigger.query])
        fixed = urlsplit(url).query
        url = urlsplit(url)._replace(query=f"{fixed}&{query}" if fixed else query).geturl()
    # The form the HTTP client sends, so a signature over the URL matches what the agent receives.
    url = str(URL(url, encoded=True))
    body = b"" if trigger.body is None else json.dumps(fill(trigger.body)).encode()
    # A secret in a query value travels percent-encoded, and an echo of the URL shows it that way.
    masked = {*carried, *(quote_plus(secret) for secret in carried)}
    return RenderedTrigger(trigger.method, url, headers, body, tuple(masked))


def agent_data_names(trigger: Trigger) -> set[str]:
    """The agent data a scenario must provide for this trigger, by normalized fact name."""
    return {
        normalized(name.partition(".")[2])
        for text in trigger.template_texts()
        for name in placeholders(text)
        if name.startswith("agent_data.")
    }


def check_agent_data(trigger: Trigger, scenario: ScenarioConfig, name: str | None = None) -> None:
    """Refuse a scenario that lacks agent data the trigger needs; the refusal names the
    scenario when its name is given."""
    have = {normalized(name) for name in scenario.agent_data_names}
    missing = sorted(agent_data_names(trigger) - have)
    if missing:
        subject = "the scenario" if name is None else f'the scenario "{name}"'
        raise ValidationError(f"{subject} has no agent data named {', '.join(missing)}")
