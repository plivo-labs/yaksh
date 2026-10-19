import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from yaksh.domain.agents import Direction
from yaksh.domain.languages import AgentLanguage
from yaksh.domain.numbers import AccountNumber
from yaksh.domain.triggers import Endpoint, TriggerMethod

MAX_CURL_CHARS = 100_000


class ImportProvider(StrEnum):
    PLIVO_CX = "plivo_cx"


class AgentFile(BaseModel):
    content: str
    """The file's text, as it is."""


class AgentDraft(BaseModel):
    """The fields an agent file fills. Nothing is saved: the person adds the rest, such as the
    brief and how Yaksh reaches the agent, then creates the agent."""

    provider: ImportProvider
    name: str | None
    external_id: str | None
    languages: list[AgentLanguage]
    language_note: str | None = None
    """The agent's language codes that Yaksh does not know; the person chooses."""
    config: str


class CurlCommand(BaseModel):
    command: str = Field(max_length=MAX_CURL_CHARS)


class Pair(BaseModel):
    name: str
    value: str


class StartRequestDraft(BaseModel):
    """A start request read from a cURL command, for the person to check. `number_field` names
    the body field or query parameter that now holds `{{yaksh.number}}`, if one looked like the
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


class ProviderDraft(BaseModel):
    """The fields an agent read from a provider fills. An agent that answers calls gives the
    numbers that reach it; an agent that calls out gives the start request instead."""

    name: str | None
    external_id: str
    languages: list[AgentLanguage]
    language_note: str | None = None
    """The agent's language codes that Yaksh does not know; the person chooses."""
    config: str
    direction: Direction
    agent_numbers: list[str]
    start_request: StartRequestDraft | None
    endpoint: Endpoint | None = None
    """The agent's text endpoint, when the provider serves Yaksh's text contract."""
    agent_speaks_first: bool = True
    number_note: str | None = None
    """Why an agent that answers calls has no number: none reaches it, or the lookup failed.
    The person enters the number."""


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


class ElevenLabsRegion(StrEnum):
    """Where the ElevenLabs workspace is. EU, India and Singapore workspaces are separate, with
    their own API host and keys."""

    GLOBAL = "global"
    EU = "eu"
    IN = "in"
    SG = "sg"


class ElevenLabsAccount(BaseModel):
    """An ElevenLabs API key, used for one import and never stored."""

    api_key: str = Field(min_length=1, max_length=200)
    region: ElevenLabsRegion = ElevenLabsRegion.GLOBAL


class ElevenLabsAgentSearch(ElevenLabsAccount):
    name: str | None = Field(default=None, max_length=200)
    cursor: str | None = Field(default=None, max_length=2000)


class ElevenLabsAgentChoice(ElevenLabsAccount):
    agent_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")


class ElevenLabsAgent(BaseModel):
    id: str
    name: str
    last_call_at: datetime | None


class ElevenLabsAgentPage(BaseModel):
    items: list[ElevenLabsAgent]
    next_cursor: str | None
    """Where the next page starts, or None after the last."""


class ElevenLabsAccountApi(Protocol):
    """The ElevenLabs calls an import makes, with the workspace's own key. A failed call raises
    ProviderCallError with ElevenLabs' status."""

    api_key: str
    base_url: str

    async def list_agents(self, *, name: str | None, cursor: str | None) -> dict[str, Any]:
        """Agents that are not archived."""
        ...

    async def get_agent(self, agent_id: str) -> dict[str, Any]: ...

    async def get_tool(self, tool_id: str) -> dict[str, Any]: ...

    async def outbound_numbers(self) -> list[dict[str, Any]]:
        """The workspace's numbers that can place calls."""
        ...


VAPI_PAGE_SIZE = 100
"""The assistants in one Vapi list call; a shorter page is the last."""


class VapiRegion(StrEnum):
    """Where the Vapi organization is. An EU organization has its own API host and keys."""

    US = "us"
    EU = "eu"


class VapiAccount(BaseModel):
    """A Vapi private API key, used for one import and never stored."""

    api_key: str = Field(min_length=1, max_length=200)
    region: VapiRegion = VapiRegion.US


class VapiAssistantSearch(VapiAccount):
    name: str | None = Field(default=None, max_length=200)
    cursor: datetime | None = None
    """The creation time of the last assistant shown: the next page has older ones."""


class VapiAssistantChoice(VapiAccount):
    assistant_id: uuid.UUID


class VapiAssistant(BaseModel):
    id: str
    name: str
    updated_at: datetime | None
    numbers: list[str]
    """The numbers that reach the assistant; without one, an import makes it call out."""


class VapiAssistantPage(BaseModel):
    items: list[VapiAssistant]
    next_cursor: datetime | None
    """Where the next page starts, or None after the last."""


class VapiAccountApi(Protocol):
    """The Vapi calls an import makes, with the organization's own key. A failed call raises
    ProviderCallError with Vapi's status."""

    api_key: str
    base_url: str

    async def list_assistants(self, *, created_before: datetime | None) -> list[dict[str, Any]]:
        """The newest assistants first, created before `created_before` when it is set."""
        ...

    async def get_assistant(self, assistant_id: str) -> dict[str, Any]: ...

    async def get_tool(self, tool_id: str) -> dict[str, Any]: ...

    async def phone_numbers(self) -> list[dict[str, Any]]: ...


RETELL_PAGE_SIZE = 100
"""The agents in one Retell list call."""


class RetellAccount(BaseModel):
    """A Retell API key, used for one import and never stored."""

    api_key: str = Field(min_length=1, max_length=200)


class RetellAgentSearch(RetellAccount):
    name: str | None = Field(default=None, max_length=200)
    cursor: str | None = Field(default=None, max_length=2000)


class RetellAgentChoice(RetellAccount):
    agent_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")


class RetellAgent(BaseModel):
    id: str
    name: str
    updated_at: datetime | None
    numbers: list[str]
    """The numbers that reach the agent; without one, an import makes it call out."""


class RetellAgentPage(BaseModel):
    items: list[RetellAgent]
    next_cursor: str | None
    """Where the next page starts, or None after the last."""


class RetellAccountApi(Protocol):
    """The Retell calls an import makes, with the workspace's own key. A failed call raises
    ProviderCallError with Retell's status."""

    api_key: str
    base_url: str

    async def list_agents(self, *, cursor: str | None) -> dict[str, Any]:
        """One page of voice agents, each agent once."""
        ...

    async def agent_versions(self, agent_id: str) -> list[dict[str, Any]]: ...

    async def get_agent(self, agent_id: str, version: int) -> dict[str, Any]: ...

    async def get_retell_llm(self, llm_id: str, version: int | None) -> dict[str, Any]: ...

    async def get_conversation_flow(self, flow_id: str, version: int | None) -> dict[str, Any]: ...

    async def phone_numbers(self) -> list[dict[str, Any]]: ...
