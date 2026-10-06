"""Starting conversations: the checks before any of them is saved, and what each one pins."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaksha.config import Settings
from yaksha.db.models import Agent, AgentVersion, Persona, PersonaVersion, Scenario, ScenarioVersion
from yaksha.domain.agents import Direction
from yaksha.domain.background_noise import BackgroundNoise, NoiseLevel, NoiseSound
from yaksha.domain.errors import NotFoundError, ValidationError
from yaksha.domain.languages import Language
from yaksha.domain.triggers import check_agent_data
from yaksha.simulation.agents import config_of as agent_config_of
from yaksha.simulation.languages import LANGUAGES
from yaksha.simulation.numbers import PHONE_SETTINGS, outbound_problem
from yaksha.simulation.personas import config_of as persona_config_of
from yaksha.simulation.personas import live_personas
from yaksha.simulation.prompts import caller_instructions
from yaksha.simulation.scenarios import config_of as scenario_config_of


@dataclass(frozen=True)
class Inputs:
    """What a conversation starts from, named as its columns. A retry copies these, and
    nothing its attempt got while running."""

    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    direction: Direction
    persona_id: uuid.UUID
    persona_version_id: uuid.UUID
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    language: Language
    instructions: str
    nudge: str
    today: date
    """The date the caller is told is today; a judge must use the same one."""
    time_zone: str
    background_noise_sound: NoiseSound
    background_noise_level: NoiseLevel


async def snapshot(
    session: AsyncSession,
    settings: Settings,
    agent: Agent,
    scenario_ids: Sequence[uuid.UUID],
    persona_id: uuid.UUID | None = None,
    background_noise: BackgroundNoise | None = None,
) -> list[Inputs]:
    """Check that conversations of the agent's scenarios can start now, and read what they pin,
    once for all of them: the current agent, scenario and persona versions, and today. Each
    scenario runs with its own persona, or with persona_id when one is given, and plays
    background_noise when one is given, else its persona's. The caller holds the agent's lock.
    A refusal about a scenario names it."""
    if not settings.phone_enabled:
        raise ValidationError(f"phone calls are off: {PHONE_SETTINGS}")
    if agent.direction is Direction.OUTBOUND:
        problem = await outbound_problem(session, settings)
        if problem is not None:
            raise ValidationError(f"outbound tests are off: {problem}")
    scenarios = await scenarios_to_start(session, agent, scenario_ids)
    chosen = [persona_id if persona_id is not None else s.persona_id for s in scenarios]
    personas = await live_personas(session, chosen, share_lock=True)
    agent_version_id = (
        await session.execute(
            select(AgentVersion.id).where(
                AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
            )
        )
    ).scalar_one()
    scenario_versions = dict(
        (
            await session.execute(
                select(ScenarioVersion.scenario_id, ScenarioVersion.id)
                .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
                .where(
                    Scenario.id.in_(scenario_ids),
                    ScenarioVersion.version == Scenario.current_version,
                )
            )
        )
        .tuples()
        .all()
    )
    persona_versions = dict(
        (
            await session.execute(
                select(PersonaVersion.persona_id, PersonaVersion.id)
                .join(Persona, Persona.id == PersonaVersion.persona_id)
                .where(
                    Persona.id.in_(personas.keys()),
                    PersonaVersion.version == Persona.current_version,
                )
            )
        )
        .tuples()
        .all()
    )
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    outbound = agent_config_of(agent).outbound if agent.direction is Direction.OUTBOUND else None
    inputs = []
    for scenario, persona in zip(scenarios, (personas[pid] for pid in chosen), strict=True):
        config = persona_config_of(persona)
        noise = background_noise if background_noise is not None else config.background_noise
        wants = scenario_config_of(scenario)
        if outbound is not None:
            check_agent_data(outbound.trigger, wants, scenario.name)
        inputs.append(
            Inputs(
                agent_id=agent.id,
                agent_version_id=agent_version_id,
                direction=agent.direction,
                persona_id=persona.id,
                persona_version_id=persona_versions[persona.id],
                scenario_id=scenario.id,
                scenario_version_id=scenario_versions[scenario.id],
                language=config.language,
                instructions=caller_instructions(
                    config,
                    goal=wants.goal,
                    known_facts=wants.known_facts,
                    unknown_facts=wants.unknown_facts,
                    today=today,
                    direction=agent.direction,
                ),
                nudge=LANGUAGES[config.language].nudge,
                today=today,
                time_zone=settings.timezone,
                background_noise_sound=noise.sound,
                background_noise_level=noise.level,
            )
        )
    return inputs


async def scenarios_to_start(
    session: AsyncSession, agent: Agent, scenario_ids: Sequence[uuid.UUID]
) -> list[Scenario]:
    """The agent's live scenarios in the order asked, share-locked in id order: edits and
    deletes wait, references such as a copied agent do not."""
    rows = await session.scalars(
        select(Scenario)
        .where(Scenario.id.in_(scenario_ids))
        .order_by(Scenario.id)
        .with_for_update(read=True)
    )
    found = {row.id: row for row in rows}
    for scenario_id in scenario_ids:
        scenario = found.get(scenario_id)
        if scenario is None or scenario.deleted_at is not None:
            raise NotFoundError(f"scenario {scenario_id} not found")
        if scenario.agent_id != agent.id:
            raise ValidationError(f'the scenario "{scenario.name}" belongs to another agent')
    return [found[scenario_id] for scenario_id in scenario_ids]
