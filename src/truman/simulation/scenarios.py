import uuid
from datetime import UTC, datetime
from typing import Any

import pydantic
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import Scenario, ScenarioVersion
from truman.domain.errors import ConflictError, NotFoundError, ValidationError
from truman.domain.scenarios import (
    SCENARIO_LABELS,
    AssignPersona,
    ScenarioConfig,
    ScenarioCreate,
    ScenarioDelete,
    ScenarioUpdate,
)
from truman.simulation.agents import get_agent
from truman.simulation.personas import get_persona

NAME_INDEX = "ix_scenarios_agent_name_live"


def config_of(scenario: Scenario) -> ScenarioConfig:
    return ScenarioConfig.model_validate(scenario.config)


def validate_config(data: dict[str, Any]) -> ScenarioConfig:
    try:
        return ScenarioConfig.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc


async def flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if NAME_INDEX in str(exc.orig):
            raise ConflictError("name is already used by another scenario of this agent") from exc
        raise


async def existing_scenario(
    session: AsyncSession, scenario_id: uuid.UUID, *, lock: bool = False
) -> Scenario:
    scenario = await session.get(
        Scenario, scenario_id, with_for_update=lock, populate_existing=lock
    )
    if scenario is None:
        raise NotFoundError("scenario not found")
    return scenario


async def get_scenario(
    session: AsyncSession, scenario_id: uuid.UUID, *, lock: bool = False
) -> Scenario:
    scenario = await existing_scenario(session, scenario_id, lock=lock)
    if scenario.deleted_at is not None:
        raise NotFoundError("scenario not found")
    return scenario


async def create_scenario(
    session: AsyncSession,
    agent_id: uuid.UUID,
    command: ScenarioCreate,
    *,
    generation_id: uuid.UUID | None = None,
) -> Scenario:
    """The agent row is locked first, so a scenario cannot be added to an agent being deleted,
    then the persona row, so the persona cannot be deleted before the scenario uses it."""
    agent = await get_agent(session, agent_id, lock=True)
    persona = await get_persona(session, command.persona_id, lock=True)
    config = command.to_config()
    scenario = Scenario(
        agent_id=agent.id,
        persona_id=persona.id,
        name=command.name,
        category=command.category,
        description=command.description or None,
        generation_id=generation_id,
        config=config.model_dump(mode="json"),
        current_version=1,
    )
    session.add(scenario)
    await flush(session)
    session.add(
        ScenarioVersion(scenario_id=scenario.id, version=1, config=config.model_dump(mode="json"))
    )
    await session.commit()
    return scenario


async def list_scenarios(
    session: AsyncSession,
    agent_id: uuid.UUID,
    *,
    offset: int,
    limit: int,
    generation_id: uuid.UUID | None = None,
) -> tuple[list[Scenario], int]:
    agent = await get_agent(session, agent_id)
    query = select(Scenario).where(Scenario.agent_id == agent.id, Scenario.deleted_at.is_(None))
    if generation_id:
        query = query.where(Scenario.generation_id == generation_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Scenario.created_at.desc(), Scenario.id).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def update_scenario(
    session: AsyncSession, scenario_id: uuid.UUID, update: ScenarioUpdate
) -> Scenario:
    """Labels and the persona change in place; a changed config writes the next version. The
    merge reads the config under the row lock, so two concurrent changes cannot drop each
    other."""
    scenario = await get_scenario(session, scenario_id, lock=True)
    changes = update.changes()
    if "persona_id" in changes:
        scenario.persona_id = (await get_persona(session, changes.pop("persona_id"), lock=True)).id
    if "description" in changes:
        changes["description"] = changes["description"] or None
    for field in SCENARIO_LABELS & changes.keys():
        setattr(scenario, field, changes.pop(field))
    if changes:
        current = config_of(scenario)
        new = validate_config({**current.model_dump(), **changes})
        if new != current:
            scenario.config = new.model_dump(mode="json")
            scenario.current_version += 1
            session.add(
                ScenarioVersion(
                    scenario_id=scenario.id,
                    version=scenario.current_version,
                    config=new.model_dump(mode="json"),
                )
            )
    await flush(session)
    await session.refresh(scenario)
    await session.commit()
    return scenario


async def delete_scenario(session: AsyncSession, scenario_id: uuid.UUID) -> None:
    scenario = await get_scenario(session, scenario_id, lock=True)
    scenario.deleted_at = datetime.now(UTC)
    await session.commit()


async def locked_scenarios(
    session: AsyncSession, agent_id: uuid.UUID, scenario_ids: list[uuid.UUID], action: str
) -> list[Scenario]:
    """The agent's live scenarios with these ids, locked in id order like every lock on several
    scenarios; all of them, or NotFoundError. The agent row is locked first, as agent deletion
    does before it changes the scenarios, so the two cannot deadlock."""
    agent = await get_agent(session, agent_id, lock=True)
    ids = set(scenario_ids)
    rows = list(
        await session.scalars(
            select(Scenario)
            .where(
                Scenario.id.in_(ids),
                Scenario.agent_id == agent.id,
                Scenario.deleted_at.is_(None),
            )
            .order_by(Scenario.id)
            .with_for_update()
        )
    )
    if len(rows) != len(ids):
        raise NotFoundError(f"a scenario to {action} was not found")
    return rows


async def delete_scenarios(
    session: AsyncSession, agent_id: uuid.UUID, command: ScenarioDelete
) -> None:
    now = datetime.now(UTC)
    for row in await locked_scenarios(session, agent_id, command.scenario_ids, "delete"):
        row.deleted_at = now
    await session.commit()


async def assign_persona(
    session: AsyncSession, agent_id: uuid.UUID, command: AssignPersona
) -> None:
    """The scenarios are locked before the persona, the same order as a single update."""
    rows = await locked_scenarios(session, agent_id, command.scenario_ids, "change")
    persona = await get_persona(session, command.persona_id, lock=True)
    for row in rows:
        row.persona_id = persona.id
    await session.commit()


async def list_versions(
    session: AsyncSession, scenario_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[list[ScenarioVersion], int]:
    scenario = await existing_scenario(session, scenario_id)
    query = select(ScenarioVersion).where(ScenarioVersion.scenario_id == scenario.id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(ScenarioVersion.version.desc()).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def get_version(
    session: AsyncSession, scenario_id: uuid.UUID, version: int
) -> ScenarioVersion:
    scenario = await existing_scenario(session, scenario_id)
    row = await session.scalar(
        select(ScenarioVersion).where(
            ScenarioVersion.scenario_id == scenario.id, ScenarioVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError("scenario version not found")
    return row
