"""Writes test scenarios from an agent's brief, config and knowledge base: a planner call lists
what to test, code spreads the requested count over it, and one writer call per slot writes a
scenario, which is checked and saved as soon as it arrives."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio
import pydantic
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksha.db.models import AgentVersion, Document, Scenario, ScenarioGeneration
from yaksha.domain.agents import AgentConfig, Direction
from yaksha.domain.errors import NotFoundError, UnavailableError, ValidationError
from yaksha.domain.generation import (
    MAX_PLANNER_CHARS,
    Capability,
    GenerateScenarios,
    GenerationMode,
    GenerationStatus,
    Priority,
    Question,
    Slot,
    agent_slots,
    grounded,
    normalized_text,
    question_slots,
    spread_personas,
)
from yaksha.domain.language_models import JsonModel
from yaksha.domain.scenarios import ScenarioCreate
from yaksha.domain.triggers import agent_data_names, check_agent_data
from yaksha.simulation import scenarios
from yaksha.simulation.agents import get_agent
from yaksha.simulation.generation_prompts import (
    CAPABILITIES_SCHEMA,
    CAPABILITIES_SYSTEM,
    QUESTIONS_SCHEMA,
    QUESTIONS_SYSTEM,
    SCENARIO_SCHEMA,
    SCENARIO_SYSTEM,
    context_text,
    planner_input,
    writer_input,
)
from yaksha.simulation.personas import live_personas

WRITERS = 4
"""Writer calls at once."""
MAX_CRITERIA = 10
MAX_NAME_CHARS = 80
MODEL_OFF = "scenario generation is off: add the LLM provider key in Settings"


@dataclass(frozen=True)
class Prepared:
    """Everything a generation reads, checked before any model call."""

    model: JsonModel
    """The model the generation runs on, checked to exist."""
    command: GenerateScenarios
    agent_id: uuid.UUID
    agent_name: str
    agent_version_id: uuid.UUID
    agent: AgentConfig
    documents: list[tuple[str, str]]
    """Name and text of each document the planner reads."""
    existing: list[tuple[str, str]]
    """Name and goal of each scenario the agent has."""

    def context(self) -> str:
        """What the planner reads: in knowledge base mode, the brief and the chosen documents
        only."""
        config = None if self.command.mode is GenerationMode.KNOWLEDGE_BASE else self.agent.config
        return context_text(self.agent.brief, config, self.documents)


@dataclass(frozen=True)
class Plan:
    slots: list[Slot]
    areas: list[str]
    """What the agent handles, in a line each, for every writer."""


@dataclass(frozen=True)
class Started:
    generation_id: uuid.UUID


@dataclass(frozen=True)
class Planned:
    count: int


@dataclass(frozen=True)
class Saved:
    scenario: Scenario


@dataclass(frozen=True)
class Dropped:
    reason: str


@dataclass(frozen=True)
class Finished:
    status: GenerationStatus
    saved: int
    dropped: int
    error: str | None = None


Event = Started | Planned | Saved | Dropped | Finished


async def prepare(
    session: AsyncSession,
    model: JsonModel | None,
    agent_id: uuid.UUID,
    command: GenerateScenarios,
) -> Prepared:
    if model is None:
        raise UnavailableError(MODEL_OFF)
    agent = await get_agent(session, agent_id)
    await live_personas(session, command.persona_ids)
    version = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version
        )
    )
    assert version is not None
    config = AgentConfig.model_validate(version.config)
    names = {entry.document_id: entry.name for entry in config.knowledge_base}
    if command.mode is GenerationMode.KNOWLEDGE_BASE:
        foreign = [str(i) for i in command.document_ids if i not in names]
        if foreign:
            raise ValidationError(f"not in the agent's knowledge base: {', '.join(foreign)}")
        chosen = command.document_ids
    else:
        chosen = list(names)
    texts = dict(
        (await session.execute(select(Document.id, Document.text).where(Document.id.in_(chosen))))
        .tuples()
        .all()
    )
    prepared = Prepared(
        model=model,
        command=command,
        agent_id=agent.id,
        agent_name=agent.name,
        agent_version_id=version.id,
        agent=config,
        documents=[(names[document_id], texts[document_id]) for document_id in chosen],
        existing=[
            (row.name, row.config["goal"])
            for row in await session.scalars(
                select(Scenario)
                .where(Scenario.agent_id == agent.id, Scenario.deleted_at.is_(None))
                .order_by(Scenario.created_at)
            )
        ],
    )
    size = len(prepared.context())
    if size > MAX_PLANNER_CHARS:
        raise ValidationError(
            f"the agent's context has {size:,} characters; the limit is {MAX_PLANNER_CHARS:,}. "
            "Use knowledge base mode with fewer documents, or shorten the config."
        )
    return prepared


async def generate(
    sessionmaker: async_sessionmaker[AsyncSession], prepared: Prepared
) -> AsyncGenerator[Event]:
    """The events of one generation. Closing the iterator, or cancelling it when the console
    disconnects, stops it: what is saved stays, and the generation is recorded as stopped."""
    command = prepared.command
    model = prepared.model
    # Shielded, so a committed row always reaches the finally below.
    with anyio.CancelScope(shield=True):
        async with sessionmaker() as session:
            row = ScenarioGeneration(
                agent_id=prepared.agent_id,
                agent_version_id=prepared.agent_version_id,
                mode=command.mode,
                count=command.count,
                instructions=command.instructions,
                document_ids=[str(document_id) for document_id in command.document_ids],
            )
            session.add(row)
            await session.commit()
            generation_id = row.id
    writer = Writer(sessionmaker, model, prepared, generation_id)
    status, error, saved = GenerationStatus.STOPPED, None, 0
    try:
        yield Started(generation_id)
        planned = await plan(model, prepared)
        if planned.slots:
            yield Planned(len(planned.slots))
            async with aclosing(writer.write_all(planned)) as written:
                async for event in written:
                    yield event
            status = GenerationStatus.DONE
        else:
            status, error = GenerationStatus.FAILED, "the agent's context shows nothing to test"
    except (UnavailableError, NotFoundError) as failure:
        status, error = GenerationStatus.FAILED, str(failure)
    except Exception:
        status, error = GenerationStatus.FAILED, "the generation failed"
        raise
    finally:
        # The console's disconnect cancels this generator; the record must still be written.
        with anyio.CancelScope(shield=True):
            saved = await record_end(sessionmaker, generation_id, status, writer.dropped, error)
    yield Finished(status, saved, writer.dropped, error)


async def record_end(
    sessionmaker: async_sessionmaker[AsyncSession],
    generation_id: uuid.UUID,
    status: GenerationStatus,
    dropped: int,
    error: str | None,
) -> int:
    """Records how the generation ended. The saved count is the scenarios in the database,
    so it is right however the generation stopped."""
    async with sessionmaker() as session:
        saved = await session.scalar(
            select(func.count()).where(Scenario.generation_id == generation_id)
        )
        await session.execute(
            update(ScenarioGeneration)
            .where(ScenarioGeneration.id == generation_id)
            .values(
                status=status,
                saved=saved or 0,
                dropped=dropped,
                error=error,
                ended_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return saved or 0


async def plan(model: JsonModel, prepared: Prepared) -> Plan:
    command = prepared.command
    context = prepared.context()
    user = planner_input(
        prepared.agent_name, prepared.agent, context, prepared.existing, command.instructions
    )
    if command.mode is GenerationMode.KNOWLEDGE_BASE:
        answer = (
            await model.complete_json(
                system=QUESTIONS_SYSTEM, user=user, name="questions", schema=QUESTIONS_SCHEMA
            )
        ).data
        answered, unanswered = grounded_questions(answer, prepared.documents)
        return Plan(
            question_slots(answered, unanswered, command.count),
            [question.question for question in answered],
        )
    answer = (
        await model.complete_json(
            system=CAPABILITIES_SYSTEM, user=user, name="capabilities", schema=CAPABILITIES_SCHEMA
        )
    ).data
    capabilities = grounded_capabilities(answer, normalized_text(context))
    return Plan(
        agent_slots(capabilities, command.count),
        [
            f"{capability.name}: {capability.what_it_does}"
            for capability in capabilities
            if capability.priority is not Priority.BOUNDARY
        ],
    )


def grounded_capabilities(answer: dict[str, Any], context: str) -> list[Capability]:
    """The planner's capabilities with at least one quote that is really in the context."""
    kept = []
    for item in answer.get("capabilities", []):
        quotes = tuple(q for q in item["quotes"] if grounded(normalized_text(q), context))
        if quotes:
            kept.append(
                Capability(
                    name=item["name"],
                    what_it_does=item["what_it_does"],
                    priority=Priority(item["priority"]),
                    quotes=quotes,
                    already_tested=item["already_tested"],
                )
            )
    return kept


def grounded_questions(
    answer: dict[str, Any], documents: Sequence[tuple[str, str]]
) -> tuple[list[Question], list[Question]]:
    """Answered questions whose quote is really in the named document, and the unanswered."""
    texts = {name.lower(): normalized_text(text) for name, text in documents}
    answered = [
        Question(item["question"], item["answer"], item["document"], item["quote"])
        for item in answer.get("answered", [])
        if grounded(normalized_text(item["quote"]), texts.get(item["document"].lower(), ""))
    ]
    unanswered = [
        Question(item["question"], None, None, None) for item in answer.get("unanswered", [])
    ]
    return answered, unanswered


def free_name(name: str, taken: set[str]) -> str:
    """The name, or the name with " (2)", " (3)"… when it is taken, within the name limit."""
    candidate, n = name, 2
    while candidate.lower() in taken:
        suffix = f" ({n})"
        candidate = f"{name[: MAX_NAME_CHARS - len(suffix)]}{suffix}"
        n += 1
    return candidate


class Writer:
    """Writes, checks and saves one scenario per slot, a few at a time, each retried once."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        model: JsonModel,
        prepared: Prepared,
        generation_id: uuid.UUID,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._model = model
        self._prepared = prepared
        self._generation_id = generation_id
        self._gate = asyncio.Semaphore(WRITERS)
        self.dropped = 0
        agent = prepared.agent
        outbound = agent.outbound if agent.direction is Direction.OUTBOUND else None
        self._trigger = outbound.trigger if outbound else None
        self._agent_data = sorted(agent_data_names(self._trigger)) if self._trigger else []

    async def write_all(self, plan: Plan) -> AsyncGenerator[Saved | Dropped]:
        personas = spread_personas(plan.slots, self._prepared.command.persona_ids)
        tasks = [
            asyncio.ensure_future(self.write(slot, persona_id, plan))
            for slot, persona_id in zip(plan.slots, personas, strict=True)
        ]
        try:
            for next_done in asyncio.as_completed(tasks):
                yield await next_done
        finally:
            for task in tasks:
                task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)

    async def write(self, slot: Slot, persona_id: uuid.UUID, plan: Plan) -> Saved | Dropped:
        reason = ""
        for _ in range(2):
            async with self._gate:
                try:
                    command = self.checked(await self.ask(slot, plan), slot, persona_id)
                except (UnavailableError, ValidationError) as error:
                    reason = str(error)
                    continue
            return Saved(await self.save(command))
        self.dropped += 1
        return Dropped(reason)

    async def ask(self, slot: Slot, plan: Plan) -> dict[str, Any]:
        prepared = self._prepared
        user = writer_input(
            prepared.agent_name,
            prepared.agent,
            self._agent_data,
            plan.areas,
            slot,
            plan.slots,
            prepared.existing,
            prepared.command.instructions,
        )
        return (
            await self._model.complete_json(
                system=SCENARIO_SYSTEM, user=user, name="scenario", schema=SCENARIO_SCHEMA
            )
        ).data

    def checked(self, answer: dict[str, Any], slot: Slot, persona_id: uuid.UUID) -> ScenarioCreate:
        """The written scenario as the API would take it, or why it cannot be saved."""
        try:
            command = ScenarioCreate.model_validate(
                {
                    **answer,
                    "category": slot.category,
                    "persona_id": persona_id,
                    "criteria": answer["criteria"][:MAX_CRITERIA],
                    "agent_data": answer["agent_data"] if self._agent_data else [],
                }
            )
        except pydantic.ValidationError as error:
            message = error.errors()[0]["msg"]
            raise ValidationError(f"the written scenario is not valid: {message}") from error
        if self._trigger is not None:
            check_agent_data(self._trigger, command.to_config())
        return command

    async def save(self, command: ScenarioCreate) -> Scenario:
        """Saves under the agent's row lock, so the free name is still free when it is used."""
        agent_id = self._prepared.agent_id
        async with self._sessionmaker() as session:
            await get_agent(session, agent_id, lock=True)
            taken = set(
                await session.scalars(
                    select(func.lower(Scenario.name)).where(
                        Scenario.agent_id == agent_id, Scenario.deleted_at.is_(None)
                    )
                )
            )
            named = command.model_copy(update={"name": free_name(command.name, taken)})
            return await scenarios.create_scenario(
                session, agent_id, named, generation_id=self._generation_id
            )


async def list_generations(
    session: AsyncSession, agent_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[list[tuple[ScenarioGeneration, int]], int]:
    """The agent's generations that still have scenarios, newest first, each with how many."""
    agent = await get_agent(session, agent_id)
    live = func.count(Scenario.id).label("live")
    query = (
        select(ScenarioGeneration, live)
        .join(Scenario, Scenario.generation_id == ScenarioGeneration.id)
        .where(ScenarioGeneration.agent_id == agent.id, Scenario.deleted_at.is_(None))
        .group_by(ScenarioGeneration.id)
    )
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(ScenarioGeneration.created_at.desc(), ScenarioGeneration.id)
        .offset(offset)
        .limit(limit)
    )
    return [(row, count) for row, count in rows.tuples()], total or 0
