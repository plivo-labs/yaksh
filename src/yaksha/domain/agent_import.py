import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from yaksha.domain.agents import Direction
from yaksha.domain.languages import Language
from yaksha.domain.numbers import AccountNumber
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


class PlivoCxAccount(BaseModel):
    """A Plivo account's credentials, used for one import and never stored. The Auth ID goes
    into Plivo's URL path, so it must have Plivo's shape."""

    auth_id: str = Field(pattern=r"^[MS]A[A-Z0-9]{18}$")
    auth_token: str = Field(min_length=1, max_length=200)


class PlivoCxFlowSearch(PlivoCxAccount):
    name: str | None = Field(default=None, max_length=200)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class PlivoCxFlowChoice(PlivoCxAccount):
    flow_id: uuid.UUID


class PlivoCxFlow(BaseModel):
    id: str
    name: str
    state: str | None
    type: str | None
    """Plivo CX's flow type, such as incoming_call or api_request."""
    updated_at: datetime | None


class PlivoCxFlowPage(BaseModel):
    items: list[PlivoCxFlow]
    next_offset: int | None
    """Where the next page starts, or None after the last."""


class PlivoCxDraft(BaseModel):
    """The fields a Plivo CX agent flow fills. A flow that a call starts gives the numbers that
    reach it; a flow that a request starts gives the start request instead."""

    name: str | None
    external_id: str
    language: Language
    config: str
    direction: Direction
    agent_numbers: list[str]
    start_request: StartRequestDraft | None


class PlivoCxAccountApi(Protocol):
    """The Plivo calls an import makes, with the account's own credentials. A failed call raises
    ProviderCallError with Plivo's status."""

    auth_id: str
    auth_token: str

    async def list_agent_flows(self, *, name: str | None, offset: int) -> dict[str, Any]:
        """Active flows only: a draft or paused flow takes no calls."""
        ...

    async def get_agent_flow(self, flow_id: str) -> str: ...

    async def agent_flow_applications(self) -> dict[str, str]: ...

    async def list_numbers(self) -> list[AccountNumber]: ...
