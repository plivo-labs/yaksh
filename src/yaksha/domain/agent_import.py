from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from yaksha.domain.languages import Language
from yaksha.domain.triggers import TriggerMethod

MAX_CURL_CHARS = 100_000


class ImportProvider(StrEnum):
    PLIVO_CX = "plivo_cx"


class AgentFile(BaseModel):
    content: str
    """The file's text, as it is."""


class AgentDraft(BaseModel):
    """The fields an agent file fills. Nothing is saved: the person adds the rest, such as the
    brief and how Yaksha reaches the agent, then creates the agent."""

    provider: ImportProvider
    name: str | None
    external_id: str | None
    language: Language
    config: str


class CurlCommand(BaseModel):
    command: str = Field(max_length=MAX_CURL_CHARS)


class Pair(BaseModel):
    name: str
    value: str


class StartRequestDraft(BaseModel):
    """A start request read from a cURL command, for the person to check. `number_field` names
    the body field or query parameter that now holds `{{yaksha.number}}`, if one looked like the
    number to call."""

    method: TriggerMethod
    url: str
    headers: list[Pair]
    query: list[Pair]
    body: dict[str, Any] | None
    number_field: str | None
