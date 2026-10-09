import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pydantic
from pydantic import BaseModel
from sqlalchemy import String, cast, false, func, or_, select
from sqlalchemy import update as update_rows
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.sql.elements import ColumnElement

from yaksha.db.models import (
    Agent,
    AgentVersion,
    Conversation,
    Document,
    Scenario,
    ScenarioVersion,
)
from yaksha.domain.agents import (
    AgentConfig,
    AgentCreate,
    AgentSource,
    AgentUpdate,
    Direction,
)
from yaksha.domain.conversations import ACTIVE_STATUSES
from yaksha.domain.errors import ConflictError, NotFoundError, ValidationError

IDENTITY_FIELDS = frozenset({"name", "external_id"})
EXTERNAL_ID_INDEX = "ix_agents_external_id_live"
SORT_KEYS = {
    "name": func.lower(Agent.name),
    "language": Agent.language,
    "created_at": Agent.created_at,
    "updated_at": Agent.updated_at,
}
"""Columns an agent list sorts on; `-` before a key sorts descending."""
PHONE_LIKE = re.compile(r"[\d\s+().-]+")


def config_of(agent: Agent) -> AgentConfig:
    return AgentConfig.model_validate(
        {field: getattr(agent, field) for field in AgentConfig.model_fields}
    )


def column_value(value: Any) -> Any:
    """Nested settings are stored as JSON."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [column_value(item) for item in value]
    return value


def apply_config(agent: Agent, config: AgentConfig) -> None:
    for field in AgentConfig.model_fields:
        setattr(agent, field, column_value(getattr(config, field)))


def validate_config(data: dict[str, Any]) -> AgentConfig:
    try:
        return AgentConfig.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc


async def check_documents(session: AsyncSession, config: AgentConfig) -> None:
    wanted = {entry.document_id for entry in config.knowledge_base}
    found = set(await session.scalars(select(Document.id).where(Document.id.in_(wanted))))
    missing = sorted(str(document_id) for document_id in wanted - found)
    if missing:
        raise ValidationError(f"knowledge_base: no document {', '.join(missing)}")


async def knowledge_base_documents(
    session: AsyncSession, agent: Agent
) -> dict[uuid.UUID, Document]:
    """The agent's knowledge base documents by id, without their text."""
    ids = [uuid.UUID(entry["document_id"]) for entry in agent.knowledge_base]
    rows = await session.scalars(
        select(Document).where(Document.id.in_(ids)).options(defer(Document.text))
    )
    return {row.id: row for row in rows}


async def flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if EXTERNAL_ID_INDEX in str(exc.orig):
            raise ConflictError("external_id is already used by another agent") from exc
        raise


async def existing_agent(
    session: AsyncSession, agent_id: uuid.UUID, *, lock: bool = False
) -> Agent:
    agent = await session.get(Agent, agent_id, with_for_update=lock)
    if agent is None:
        raise NotFoundError("agent not found")
    return agent


async def get_agent(session: AsyncSession, agent_id: uuid.UUID, *, lock: bool = False) -> Agent:
    agent = await existing_agent(session, agent_id, lock=lock)
    if agent.deleted_at is not None:
        raise NotFoundError("agent not found")
    return agent


async def add_agent(
    session: AsyncSession,
    name: str,
    external_id: str | None,
    source: AgentSource,
    config: AgentConfig,
) -> Agent:
    agent = Agent(name=name, external_id=external_id, source=source, current_version=1)
    apply_config(agent, config)
    session.add(agent)
    await flush(session)
    session.add(AgentVersion(agent_id=agent.id, version=1, config=config.model_dump(mode="json")))
    return agent


async def create_agent(session: AsyncSession, command: AgentCreate) -> Agent:
    config = command.to_config()
    await check_documents(session, config)
    agent = await add_agent(session, command.name, command.external_id, command.source, config)
    await session.commit()
    return agent


async def duplicate_agent(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    """A new agent with the same configuration and a copy of every live scenario, all at
    version 1. The external id stays with the original, since it names that agent."""
    source = await get_agent(session, agent_id, lock=True)
    agent = await add_agent(
        session, f"{source.name} (copy)", None, source.source, config_of(source)
    )
    # Locked, so no scenario changes its persona while it is copied: a live scenario keeps its
    # persona from being deleted, and the copy then points to a live persona too.
    scenarios = list(
        await session.scalars(
            select(Scenario)
            .where(Scenario.agent_id == source.id, Scenario.deleted_at.is_(None))
            .order_by(Scenario.id)
            .with_for_update()
        )
    )
    # Copies share one creation time, so ids order them: copying newest first keeps the listing.
    scenarios.sort(key=lambda scenario: scenario.created_at, reverse=True)
    for scenario in scenarios:
        copy = Scenario(
            agent_id=agent.id,
            persona_id=scenario.persona_id,
            name=scenario.name,
            category=scenario.category,
            description=scenario.description,
            config=scenario.config,
            current_version=1,
        )
        session.add(copy)
        await session.flush()
        session.add(ScenarioVersion(scenario_id=copy.id, version=1, config=scenario.config))
    await session.commit()
    return agent


async def list_agents(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    external_id: str | None = None,
    direction: Direction | None = None,
    source: AgentSource | None = None,
    search: str | None = None,
    sort: str = "-created_at",
) -> tuple[list[Agent], int]:
    query = (
        select(Agent)
        .where(Agent.deleted_at.is_(None))
        .options(defer(Agent.config), defer(Agent.knowledge_base))
    )
    if search:
        query = query.where(matching(search))
    if external_id is not None:
        query = query.where(Agent.external_id == external_id)
    if direction is not None:
        query = query.where(Agent.direction == direction)
    if source is not None:
        query = query.where(Agent.source == source)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    key = SORT_KEYS[sort.removeprefix("-")]
    rows = await session.scalars(
        query.order_by(key.desc() if sort.startswith("-") else key.asc(), Agent.id)
        .offset(offset)
        .limit(limit)
    )
    return list(rows), total or 0


async def agent_sources(session: AsyncSession) -> list[AgentSource]:
    """The sources of the live agents, each once."""
    rows = await session.scalars(
        select(Agent.source).where(Agent.deleted_at.is_(None)).distinct().order_by(Agent.source)
    )
    return list(rows)


def matching(search: str) -> ColumnElement[bool]:
    """Name, external id or id containing the text, ignoring case; and, when the text is written
    like a phone number, a number containing its digits, so "+1 (415) 555" finds +14155550100."""
    text = search.strip()
    digits = "".join(ch for ch in search if ch.isdigit())
    dialed = PHONE_LIKE.fullmatch(search.strip()) is not None and len(digits) >= 3
    return or_(
        Agent.name.icontains(text, autoescape=True),
        Agent.external_id.icontains(text, autoescape=True),
        cast(Agent.id, String).icontains(text, autoescape=True),
        Agent.agent_number.contains(digits, autoescape=True) if dialed else false(),
    )


async def update_agent(session: AsyncSession, agent_id: uuid.UUID, update: AgentUpdate) -> Agent:
    changes = update.changes()
    agent = await get_agent(session, agent_id, lock=True)
    current = config_of(agent)
    config_changes = {k: v for k, v in changes.items() if k not in IDENTITY_FIELDS}
    new = validate_config({**current.model_dump(), **config_changes})
    # Before the agent changes: this query would flush a pending external_id clash, which
    # must reach flush() below to become a 409.
    if new.knowledge_base != current.knowledge_base:
        await check_documents(session, new)
    for field in IDENTITY_FIELDS & changes.keys():
        setattr(agent, field, changes[field])
    if new != current:
        apply_config(agent, new)
        agent.current_version += 1
        session.add(
            AgentVersion(
                agent_id=agent.id,
                version=agent.current_version,
                config=new.model_dump(mode="json"),
            )
        )
    await flush(session)
    await session.refresh(agent)
    await session.commit()
    return agent


async def delete_agent(session: AsyncSession, agent_id: uuid.UUID) -> None:
    agent = await get_agent(session, agent_id, lock=True)
    active = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.agent_id == agent.id, Conversation.status.in_(ACTIVE_STATUSES))
    )
    if active:
        raise ConflictError("agent has an active conversation")
    now = datetime.now(UTC)
    agent.deleted_at = now
    await session.execute(
        update_rows(Scenario)
        .where(Scenario.agent_id == agent.id, Scenario.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    await session.commit()


async def list_versions(
    session: AsyncSession, agent_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[list[AgentVersion], int]:
    agent = await existing_agent(session, agent_id)
    query = select(AgentVersion).where(AgentVersion.agent_id == agent.id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(AgentVersion.version.desc()).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def get_version(session: AsyncSession, agent_id: uuid.UUID, version: int) -> AgentVersion:
    agent = await existing_agent(session, agent_id)
    row = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError("agent version not found")
    return row
