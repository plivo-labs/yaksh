"""Starting conversations: the checks before any of them is saved, and what each one pins."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.config import Settings
from yaksh.db.models import Agent, AgentVersion, Persona, PersonaVersion, Scenario, ScenarioVersion
from yaksh.domain.agents import Direction, Transport, machines_answer
from yaksh.domain.answering import AnsweredBy, plays_scenario
from yaksh.domain.errors import NotFoundError, ValidationError
from yaksh.domain.languages import AgentLanguage, Language, answer_language
from yaksh.domain.runs import RunScenario
from yaksh.domain.scenarios import DataSet, ScenarioConfig
from yaksh.domain.settings import AppSettings
from yaksh.domain.speech import SttProvider
from yaksh.domain.triggers import check_agent_data
from yaksh.domain.voices import VoiceProvider
from yaksh.simulation.agents import config_of as agent_config_of
from yaksh.simulation.languages import LANGUAGES
from yaksh.simulation.numbers import inbound_problem, outbound_problem, phone_problem
from yaksh.simulation.personas import config_of as persona_config_of
from yaksh.simulation.personas import live_personas
from yaksh.simulation.prompts import caller_instructions
from yaksh.simulation.scenarios import config_of as scenario_config_of


@dataclass(frozen=True)
class Inputs:
    """What a conversation starts from, named as its columns. A retry copies these, and
    nothing its attempt got while running."""

    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    direction: Direction
    transport: Transport
    persona_id: uuid.UUID
    persona_version_id: uuid.UUID
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    data_set_id: uuid.UUID
    data_set_name: str
    answered_by: AnsweredBy
    language: Language
    instructions: str
    nudge: str
    today: date
    """The date the caller is told is today; a judge must use the same one."""
    time_zone: str
    surroundings: dict[str, Any]
    """The persona's `Surroundings`, as JSON."""


async def snapshot(
    session: AsyncSession,
    settings: Settings,
    app: AppSettings,
    agent: Agent,
    wanted: Sequence[RunScenario],
    asked: Transport | None,
) -> list[Inputs]:
    """Check that conversations of the agent's scenarios can start now, and read what they pin,
    once for all of them: the current agent, scenario and persona versions, and today. Each
    scenario runs with the personas asked for, or its own persona, each persona plays the data
    sets asked for, or every data set, and each of those calls is answered by each answer asked
    for. The inputs are in the order asked: scenario, then persona, then data set, then answer.
    The caller holds the agent's lock.
    A refusal about a scenario names it."""
    current = agent_config_of(agent)
    transport = chosen_transport(current.transports, asked)
    if transport is Transport.TEXT:
        if app.secrets.llm_api_key is None:
            raise ValidationError("text tests are off: add the LLM provider key in Settings")
    elif (problem := phone_problem(settings, app)) is not None:
        raise ValidationError(f"phone calls are off: {problem}")
    elif agent.direction is Direction.OUTBOUND:
        problem = await outbound_problem(session, settings, app)
        if problem is not None:
            raise ValidationError(f"outbound tests are off: {problem}")
    elif (problem := await inbound_problem(session, settings, app)) is not None:
        raise ValidationError(f"phone calls are off: {problem}")
    scenario_ids = [item.scenario_id for item in wanted]
    scenarios = await scenarios_to_start(session, agent, scenario_ids)
    machines = machines_answer(transport, agent.direction)
    for scenario, item in zip(scenarios, wanted, strict=True):
        if not machines and item.answered_by != [AnsweredBy.CALLER]:
            raise ValidationError(
                f'the scenario "{scenario.name}": voicemail and call screening need a phone run '
                "of an outbound agent"
            )
    plays = [
        (scenario, persona_id, data_set, answer)
        for scenario, item in zip(scenarios, wanted, strict=True)
        for persona_id in item.persona_ids or [scenario.persona_id]
        for data_set in data_sets_to_play(scenario, item.data_set_ids)
        for answer in item.answered_by
    ]
    personas = await live_personas(
        session, sorted({persona_id for _, persona_id, _, _ in plays}), share_lock=True
    )
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
    today = datetime.now(ZoneInfo(app.phone.timezone)).date()
    trigger = (
        current.outbound.trigger
        if transport is Transport.PHONE and current.outbound is not None
        else None
    )
    inputs = []
    for scenario, persona_id, data_set, answer in plays:
        persona = personas[persona_id]
        config = persona_config_of(persona)
        wants = scenario_config_of(scenario)
        if transport is Transport.PHONE:
            check_heard(app.speech.stt, current.languages, config.language, persona.name)
            check_persona_voice(app, config.voice.provider, config.language, persona.name)
            if plays_scenario(answer, picked_up=config.answering.picks_up):
                check_words_while_speaking(app.speech.stt, wants, scenario.name)
        if trigger is not None:
            check_agent_data(trigger, wants, scenario.name)
        played = wants.played(data_set.id)
        inputs.append(
            Inputs(
                agent_id=agent.id,
                agent_version_id=agent_version_id,
                direction=agent.direction,
                transport=transport,
                persona_id=persona.id,
                persona_version_id=persona_versions[persona.id],
                scenario_id=scenario.id,
                scenario_version_id=scenario_versions[scenario.id],
                data_set_id=data_set.id,
                data_set_name=data_set.name,
                answered_by=answer,
                language=config.language,
                instructions=caller_instructions(
                    config,
                    instructions=played.instructions,
                    known_facts=played.known_facts,
                    unknown_facts=played.unknown_facts,
                    today=today,
                    direction=agent.direction,
                    over_text=transport is Transport.TEXT,
                ),
                nudge=LANGUAGES[config.language].nudge,
                today=today,
                time_zone=app.phone.timezone,
                surroundings=config.surroundings.model_dump(mode="json"),
            )
        )
    return inputs


def check_heard(
    stt: SttProvider, agent: Sequence[AgentLanguage], caller: Language, persona: str
) -> None:
    """Refuse a phone call whose agent should answer in a language the speech-to-text in use
    does not hear."""
    answer = answer_language(agent, caller).language
    if answer not in stt.traits.languages:
        raise ValidationError(
            f"speech to text ({stt.label}) doesn't hear {answer.label}, which the agent "
            f'answers the persona "{persona}" in; choose another provider in Settings'
        )


def check_words_while_speaking(stt: SttProvider, scenario: ScenarioConfig, name: str) -> None:
    """Refuse a phone call whose interruption waits for a phrase when the speech to text in use
    gives the agent's words only after it stops: the line could not play."""
    if stt.traits.words_while_speaking:
        return
    for number, item in enumerate(scenario.interruptions, 1):
        if item.agent_says is not None:
            raise ValidationError(
                f'interruption {number} of the scenario "{name}" waits for a phrase, and speech to '
                f"text ({stt.label}) gives the agent's words only after it stops, so it cannot "
                "play; start it when the agent starts to talk, or choose another provider in "
                "Settings"
            )


def check_persona_voice(
    app: AppSettings, provider: VoiceProvider, language: Language, persona: str
) -> None:
    """Refuse a phone call whose persona speaks with a provider that has no key, or that does
    not speak the persona's language."""
    if app.tts_credential(provider) is None:
        raise ValidationError(
            f'phone calls are off: the persona "{persona}" uses a {provider.label} voice; add '
            f"the {provider.label} key in Settings"
        )
    if language not in provider.traits.languages:
        raise ValidationError(
            f"text to speech ({provider.label}) doesn't speak {language.label}, the language of "
            f'the persona "{persona}"; choose a voice of another provider'
        )


def chosen_transport(has: frozenset[Transport], asked: Transport | None) -> Transport:
    """The transport asked for, or the agent's only one."""
    if asked is None:
        if len(has) > 1:
            raise ValidationError("choose phone or text: the agent has both connections")
        (only,) = has
        return only
    if asked not in has:
        missing = "text endpoint" if asked is Transport.TEXT else "phone connection"
        raise ValidationError(f"the agent has no {missing}")
    return asked


def data_sets_to_play(scenario: Scenario, ids: Sequence[uuid.UUID] | None) -> list[DataSet]:
    """The scenario's data sets with these ids, in the order asked, or all of them."""
    try:
        return scenario_config_of(scenario).chosen(ids)
    except ValidationError as error:
        raise ValidationError(f'the scenario "{scenario.name}": {error}') from error


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
        if scenario is None:
            raise NotFoundError(f"scenario {scenario_id} not found")
        if scenario.deleted_at is not None:
            raise NotFoundError(f'the scenario "{scenario.name}" was deleted')
        if scenario.agent_id != agent.id:
            raise ValidationError(f'the scenario "{scenario.name}" belongs to another agent')
    return [found[scenario_id] for scenario_id in scenario_ids]
