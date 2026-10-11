import uuid
from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from yaksha.db.models import Agent, Document
from yaksha.domain.agents import AgentConfig, AgentSource, Direction, Transport
from yaksha.domain.languages import AgentLanguage
from yaksha.domain.rules import AgentRules
from yaksha.domain.triggers import OutboundConfig


class AgentSummary(BaseModel):
    """An agent without its config and knowledge base, for lists."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    external_id: str | None
    source: AgentSource
    direction: Direction
    transport: Transport
    agent_number: str | None
    outbound: OutboundConfig | None
    agent_speaks_first: bool
    languages: list[AgentLanguage]
    brief: str
    current_version: int
    forked_from_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


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
