import uuid
from datetime import UTC, datetime
from typing import Any

import pydantic
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import Agent, AgentVersion, Conversation
from truman.domain.agents import (
    AgentConfig,
    AgentCreate,
    AgentUpdate,
    Direction,
)
from truman.domain.conversations import ACTIVE_STATUSES
from truman.domain.errors import ConflictError, NotFoundError, ValidationError

IDENTITY_FIELDS = frozenset({"name", "external_id"})
EXTERNAL_ID_INDEX = "ix_agents_external_id_live"


def config_of(agent: Agent) -> AgentConfig:
    return AgentConfig.model_validate(
        {field: getattr(agent, field) for field in AgentConfig.model_fields}
    )


def apply_config(agent: Agent, config: AgentConfig) -> None:
    for field in AgentConfig.model_fields:
        setattr(agent, field, getattr(config, field))


def validate_config(data: dict[str, Any]) -> AgentConfig:
    try:
        return AgentConfig.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc


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


async def create_agent(session: AsyncSession, command: AgentCreate) -> Agent:
    config = command.config()
    agent = Agent(name=command.name, external_id=command.external_id, current_version=1)
    apply_config(agent, config)
    session.add(agent)
    await flush(session)
    session.add(
        AgentVersion(
            agent_id=agent.id,
            version=1,
            config=config.model_dump(mode="json"),
        )
    )
    await session.commit()
    return agent


async def list_agents(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    external_id: str | None = None,
    direction: Direction | None = None,
) -> tuple[list[Agent], int]:
    query = select(Agent).where(Agent.deleted_at.is_(None))
    if external_id is not None:
        query = query.where(Agent.external_id == external_id)
    if direction is not None:
        query = query.where(Agent.direction == direction)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Agent.created_at.desc(), Agent.id).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def update_agent(session: AsyncSession, agent_id: uuid.UUID, update: AgentUpdate) -> Agent:
    changes = update.changes()
    agent = await get_agent(session, agent_id, lock=True)
    for field in IDENTITY_FIELDS & changes.keys():
        setattr(agent, field, changes[field])

    config_changes = {k: v for k, v in changes.items() if k not in IDENTITY_FIELDS}
    if config_changes:
        current = config_of(agent)
        new = validate_config({**current.model_dump(), **config_changes})
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
    agent.deleted_at = datetime.now(UTC)
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
