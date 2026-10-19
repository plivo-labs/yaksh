import uuid
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from yaksh.domain.documents import DocumentName
from yaksh.domain.languages import AgentLanguage
from yaksh.domain.numbers import E164
from yaksh.domain.rules import AgentRules
from yaksh.domain.triggers import Endpoint, OutboundConfig, placeholders


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class AgentSource(StrEnum):
    """Where an agent came from: made in Yaksh, or imported from a file or a provider."""

    MANUAL = "manual"
    FILE = "file"
    PLIVO_CX = "plivo_cx"
    ELEVENLABS = "elevenlabs"
    VAPI = "vapi"
    RETELL = "retell"


class Transport(StrEnum):
    """How Yaksh reaches an agent."""

    PHONE = "phone"
    TEXT = "text"
    """Over HTTP, one request a turn, with no audio: docs/content/docs/text-tests.mdx."""


TEXT_TURN_TIMEOUT_S = 60.0
"""How long Yaksh waits for a text agent's reply to one turn."""
MIN_BRIEF_CHARS = 20
MAX_BRIEF_CHARS = 10_000
MAX_CONFIG_CHARS = 1_000_000
MAX_KNOWLEDGE_BASE_DOCUMENTS = 20


def without_nul(value: str) -> str:
    """Postgres text and jsonb cannot hold NUL, so it is dropped."""
    return value.replace("\x00", "")


def without_nul_first(value: object) -> object:
    """NUL is dropped before the length check, so twenty NULs are not a brief."""
    return without_nul(value) if isinstance(value, str) else value


Brief = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=MIN_BRIEF_CHARS, max_length=MAX_BRIEF_CHARS
    ),
    BeforeValidator(without_nul_first),
]
ConfigText = Annotated[
    str, StringConstraints(max_length=MAX_CONFIG_CHARS), AfterValidator(without_nul)
]


class KnowledgeBaseEntry(BaseModel):
    """A document the agent answers from, under the name the agent shows for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: uuid.UUID
    name: DocumentName


KnowledgeBase = Annotated[list[KnowledgeBaseEntry], Field(max_length=MAX_KNOWLEDGE_BASE_DOCUMENTS)]


def distinct_entries(entries: list[KnowledgeBaseEntry]) -> list[KnowledgeBaseEntry]:
    # lower(), not casefold(): the console checks names the same way before it saves.
    names = [entry.name.lower() for entry in entries]
    if len(set(names)) < len(names):
        raise ValueError("two knowledge base documents have the same name")
    ids = [entry.document_id for entry in entries]
    if len(set(ids)) < len(ids):
        raise ValueError("a document is in the knowledge base twice")
    return entries


def distinct_languages(languages: list[AgentLanguage]) -> list[AgentLanguage]:
    if len(set(languages)) < len(languages):
        raise ValueError("a language is listed twice")
    return languages


AgentLanguages = Annotated[
    list[AgentLanguage], Field(min_length=1), AfterValidator(distinct_languages)
]
"""The first is the agent's main language."""


def transports_of(
    direction: Direction, agent_number: object, outbound: object, endpoint: object
) -> frozenset[Transport]:
    """The ways Yaksh can reach an agent, one for each connection it has."""
    phone = agent_number if direction is Direction.INBOUND else outbound
    return frozenset(
        transport
        for transport, connection in ((Transport.PHONE, phone), (Transport.TEXT, endpoint))
        if connection is not None
    )


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Direction = Direction.INBOUND
    agent_number: E164 | None = None
    """The number Yaksh dials: the phone connection of an inbound agent."""
    outbound: OutboundConfig | None = None
    """The phone connection of an outbound agent."""
    endpoint: Endpoint | None = None
    """Where Yaksh sends each turn: the text connection."""
    agent_speaks_first: bool = True
    languages: AgentLanguages = [AgentLanguage.EN_US]
    brief: Brief
    """A short description of the agent, in the user's words."""
    config: ConfigText | None = None
    """The agent's full configuration as text, in any format: a prompt, a flow, an export."""
    knowledge_base: Annotated[KnowledgeBase, AfterValidator(distinct_entries)] = []
    rules: AgentRules = []
    """Checks for every call of the agent, beside each scenario's criteria."""

    @property
    def transports(self) -> frozenset[Transport]:
        return transports_of(self.direction, self.agent_number, self.outbound, self.endpoint)

    @model_validator(mode="after")
    def fits_direction(self) -> AgentConfig:
        if self.direction is Direction.INBOUND and self.outbound is not None:
            raise ValueError("outbound settings are only for outbound agents")
        if self.direction is Direction.OUTBOUND and self.agent_number is not None:
            raise ValueError(
                "an outbound agent has no agent_number; list the numbers it calls from "
                "in outbound.calling_numbers"
            )
        if not self.transports:
            raise ValueError(
                "an agent needs a way to reach it: agent_number for an inbound agent, outbound "
                "settings for an outbound agent, or a text endpoint"
            )
        if self.endpoint is not None:
            for header in self.endpoint.headers:
                for name in placeholders(header.value):
                    if name != "yaksh.conversation_id" and not name.startswith("secrets."):
                        raise ValueError(
                            f"a text endpoint's headers take only {{{{secrets.<NAME>}}}} and "
                            f"{{{{yaksh.conversation_id}}}}, not {{{{{name}}}}}; the agent gets "
                            "the agent data in customData"
                        )
        return self


class BriefSource(BaseModel):
    config: ConfigText


class BriefDraft(BaseModel):
    brief: str


class AgentCreate(AgentConfig):
    name: str = Field(min_length=1)
    external_id: str | None = None
    source: AgentSource = AgentSource.MANUAL
    write_scenarios: bool = True
    """Start writing the first scenarios once the agent is saved."""

    def to_config(self) -> AgentConfig:
        return AgentConfig.model_validate(
            self.model_dump(exclude={"name", "external_id", "source", "write_scenarios"})
        )


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, min_length=1)
    external_id: str | None = None
    direction: Direction | None = None
    agent_number: E164 | None = None
    outbound: OutboundConfig | None = None
    endpoint: Endpoint | None = None
    agent_speaks_first: bool | None = None
    languages: AgentLanguages | None = None
    brief: Brief | None = None
    config: ConfigText | None = None
    knowledge_base: Annotated[KnowledgeBase, AfterValidator(distinct_entries)] | None = None
    rules: AgentRules | None = None

    @field_validator("name", "languages", "brief", "knowledge_base", "rules")
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
