import uuid
from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from yaksh.db.models import Agent, Document
from yaksh.domain.agents import AgentConfig, AgentSource, Direction, Transport, transports_of
from yaksh.domain.languages import AgentLanguage
from yaksh.domain.record_sources import RecordSource
from yaksh.domain.rules import AgentRules
from yaksh.domain.triggers import Endpoint, OutboundConfig


class AgentSummary(BaseModel):
    """An agent without its config and knowledge base, for lists."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    external_id: str | None
    source: AgentSource
    direction: Direction
    agent_number: str | None
    outbound: OutboundConfig | None
    endpoint: Endpoint | None
    record_source: RecordSource | None
    agent_speaks_first: bool
    languages: list[AgentLanguage]
    brief: str
    current_version: int
    forked_from_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def transports(self) -> list[Transport]:
        """The ways a run can reach the agent, in a fixed order."""
        found = transports_of(self.direction, self.agent_number, self.outbound, self.endpoint)
        return [transport for transport in Transport if transport in found]


class KnowledgeBaseDocument(BaseModel):
    """A knowledge base entry with what the list shows about its document."""

    document_id: uuid.UUID
    name: str
    media_type: str | None
    size_bytes: int | None
    characters: int
    pages: int | None
    empty_pages: int | None


class AgentRead(AgentSummary):
    config: str | None
    knowledge_base: list[KnowledgeBaseDocument]
    rules: AgentRules

    @classmethod
    def of(cls, agent: Agent, documents: Mapping[uuid.UUID, Document]) -> AgentRead:
        entries = []
        for entry in agent.knowledge_base:
            document = documents[uuid.UUID(entry["document_id"])]
            entries.append(
                KnowledgeBaseDocument(
                    document_id=document.id,
                    name=entry["name"],
                    media_type=document.media_type,
                    size_bytes=document.size_bytes,
                    characters=document.characters,
                    pages=document.pages,
                    empty_pages=document.empty_pages,
                )
            )
        summary = AgentSummary.model_validate(agent).model_dump()
        return cls(**summary, config=agent.config, knowledge_base=entries, rules=agent.rules)


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    config: AgentConfig
    created_at: datetime
