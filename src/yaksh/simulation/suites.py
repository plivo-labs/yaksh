"""Test suites: saving them, and starting, cancelling and reading their suite runs
(docs/decisions/0034). Locks are taken in one order: a suite before the agents of its entries,
then their scenarios, then their personas, each set in id order; a suite run before its runs."""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Row, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.config import Settings
from yaksh.db.models import (
    Agent,
    Conversation,
    Persona,
    Run,
    Scenario,
    Suite,
    SuiteEntryScenario,
    SuiteEntryScenarioPersona,
    SuiteRun,
)
from yaksh.db.models import SuiteEntry as SuiteEntryRow
from yaksh.domain.agents import machines_answer
from yaksh.domain.answering import AnsweredBy
from yaksh.domain.conversations import ACTIVE_STATUSES
from yaksh.domain.errors import ConflictError, NotFoundError, ValidationError
from yaksh.domain.runs import RunScenario
from yaksh.domain.settings import AppSettings
from yaksh.domain.suites import AllScenarios, SuiteCreate, SuiteEntry, SuiteRunLink, SuiteUpdate
from yaksh.simulation.agents import config_of as agent_config_of
from yaksh.simulation.runs import (
    CallerCheck,
    PreparedRun,
    add_run,
    cancel_conversations,
    prepare_run,
    unserved_callers,
)
from yaksh.simulation.scenarios import config_of as scenario_config_of
from yaksh.simulation.starts import chosen_transport

NAME_INDEX = "ix_suites_name_live"
REQUEST_KEY_INDEX = "uq_suite_runs_request_key"


@dataclass(frozen=True)
class EntryCheck:
    """What the suite page shows of an entry, read now: its agent's name, how many scenarios
    and calls it starts, and why a start would refuse it."""

    agent_name: str
    scenarios: int
    calls: int
    problems: list[str]


async def create_suite(session: AsyncSession, command: SuiteCreate) -> Suite:
    suite = Suite(name=command.name, required_pass_percent=command.required_pass_percent)
    session.add(suite)
    await flush(session)
    await session.commit()
    await session.refresh(suite)
    return suite


async def flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if NAME_INDEX in str(exc.orig):
            raise ConflictError("name is already used by another suite") from exc
        raise


async def get_suite(session: AsyncSession, suite_id: uuid.UUID, *, lock: bool = False) -> Suite:
    suite = await session.get(Suite, suite_id, with_for_update=lock, populate_existing=lock)
    if suite is None or suite.deleted_at is not None:
        raise NotFoundError("suite not found")
    return suite


async def list_suites(session: AsyncSession, *, offset: int, limit: int) -> tuple[list[Suite], int]:
    query = select(Suite).where(Suite.deleted_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(func.lower(Suite.name), Suite.id).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def update_suite(session: AsyncSession, suite_id: uuid.UUID, update: SuiteUpdate) -> Suite:
    """A save of an older read is refused, so two editors cannot drop each other's changes."""
    suite = await get_suite(session, suite_id, lock=True)
    if update.revision != suite.revision:
        raise ConflictError("the suite changed since it was read: read it again")
    if update.entries is not None:
        await replace_entries(session, suite, update.entries)
    if update.name is not None:
        suite.name = update.name
    if update.required_pass_percent is not None:
        suite.required_pass_percent = update.required_pass_percent
    suite.revision += 1
    await flush(session)
    await session.commit()
    await session.refresh(suite)
    return suite


async def replace_entries(
    session: AsyncSession, suite: Suite, entries: Sequence[SuiteEntry]
) -> None:
    """Refuses only what is wrong in the request itself: an id that does not exist, or a
    scenario of another agent. What can also go wrong later, such as a
    deleted scenario, is kept and shown as a problem of its entry, so broken entries can be
    fixed one at a time. The rows that the entries point to are key-shared first, in the lock
    order, before the inserts take the same locks in an order of their own."""
    chosen = [item for entry in entries for item in chosen_scenarios(entry)]
    agents = await key_shared(session, Agent, {entry.agent_id for entry in entries})
    scenarios = await key_shared(session, Scenario, {item.scenario_id for item in chosen})
    asked = {persona_id for item in chosen for persona_id in item.persona_ids or []}
    own = {scenario.persona_id for scenario in scenarios.values()}
    personas = await key_shared(session, Persona, asked | own)
    for position, entry in enumerate(entries, 1):
        label = f"entry {position}"
        if entry.agent_id not in agents:
            raise ValidationError(f"{label}: agent {entry.agent_id} not found")
        for item in chosen_scenarios(entry):
            scenario = scenarios.get(item.scenario_id)
            if scenario is None:
                raise ValidationError(f"{label}: scenario {item.scenario_id} not found")
            if scenario.agent_id != entry.agent_id:
                raise ValidationError(f"{label}: the scenario belongs to another agent")
            for persona_id in item.persona_ids or []:
                if persona_id not in personas:
                    raise ValidationError(f"{label}: persona {persona_id} not found")
    await session.execute(delete(SuiteEntryRow).where(SuiteEntryRow.suite_id == suite.id))
    rows = [entry_row(suite.id, position, entry) for position, entry in enumerate(entries, 1)]
    session.add_all(rows)
    await session.flush()
    scenario_rows = [
        (
            SuiteEntryScenario(
                entry_id=row.id,
                agent_id=entry.agent_id,
                scenario_id=item.scenario_id,
                position=position,
                data_set_ids=item.data_set_ids,
                answered_by=item.answered_by,
            ),
            item.persona_ids or [scenarios[item.scenario_id].persona_id],
        )
        for row, entry in zip(rows, entries, strict=True)
        for position, item in enumerate(chosen_scenarios(entry), 1)
    ]
    session.add_all(row for row, _ in scenario_rows)
    await session.flush()
    session.add_all(
        SuiteEntryScenarioPersona(entry_scenario_id=row.id, position=position, persona_id=persona)
        for row, persona_ids in scenario_rows
        for position, persona in enumerate(persona_ids, 1)
    )


def chosen_scenarios(entry: SuiteEntry) -> list[RunScenario]:
    return [] if isinstance(entry.scenarios, AllScenarios) else entry.scenarios


def entry_row(suite_id: uuid.UUID, position: int, entry: SuiteEntry) -> SuiteEntryRow:
    return SuiteEntryRow(
        suite_id=suite_id,
        position=position,
        agent_id=entry.agent_id,
        transport=entry.transport,
        all_scenarios_answered_by=(
            entry.scenarios.answered_by if isinstance(entry.scenarios, AllScenarios) else None
        ),
        repeats=entry.repeats,
        max_duration_s=entry.max_duration_s,
        max_turns=entry.max_turns,
        max_parallel=entry.max_parallel,
        start_interval_s=entry.start_interval_s,
        max_retries=entry.max_retries,
    )


async def key_shared[M: (Agent, Scenario, Persona)](
    session: AsyncSession, model: type[M], ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, M]:
    """The rows with these ids that exist, deleted or not, key-shared in id order."""
    rows = await session.scalars(
        select(model)
        .where(model.id.in_(set(ids)))
        .order_by(model.id)
        .with_for_update(read=True, key_share=True)
    )
    return {row.id: row for row in rows}


async def delete_suite(session: AsyncSession, suite_id: uuid.UUID) -> None:
    """Refused while a suite run of the suite has a run at work. One that waits only for its
    judges does not stop the delete; the suite runs stay, with their results."""
    suite = await get_suite(session, suite_id, lock=True)
    busy = await session.scalar(
        select(Conversation.id)
        .join(Run, Run.id == Conversation.run_id)
        .join(SuiteRun, SuiteRun.id == Run.suite_run_id)
        .where(SuiteRun.suite_id == suite.id, Conversation.status.in_(ACTIVE_STATUSES))
        .limit(1)
    )
    if busy is not None:
        raise ConflictError("the suite has a suite run at work: cancel it or wait until it ends")
    suite.deleted_at = func.statement_timestamp()
    await session.commit()


async def saved_entries(
    session: AsyncSession, suite_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[SuiteEntry]]:
    """Each suite's entries, in position order, read in one statement: a save that replaces
    them meanwhile cannot leave an entry without its scenarios."""
    rows = await session.execute(
        select(
            SuiteEntryRow,
            SuiteEntryScenario,
            SuiteEntryScenarioPersona.persona_id,
        )
        .outerjoin(SuiteEntryScenario, SuiteEntryScenario.entry_id == SuiteEntryRow.id)
        .outerjoin(
            SuiteEntryScenarioPersona,
            SuiteEntryScenarioPersona.entry_scenario_id == SuiteEntryScenario.id,
        )
        .where(SuiteEntryRow.suite_id.in_(suite_ids))
        .order_by(
            SuiteEntryRow.suite_id,
            SuiteEntryRow.position,
            SuiteEntryScenario.position,
            SuiteEntryScenarioPersona.position,
        )
    )
    entries: dict[uuid.UUID, SuiteEntryRow] = {}
    scenarios: dict[uuid.UUID, dict[uuid.UUID, SuiteEntryScenario]] = defaultdict(dict)
    personas: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for entry, scenario, persona_id in rows.tuples():
        entries[entry.id] = entry
        if scenario is not None:
            scenarios[entry.id][scenario.id] = scenario
            personas[scenario.id].append(persona_id)
    found: dict[uuid.UUID, list[SuiteEntry]] = {suite_id: [] for suite_id in suite_ids}
    for entry in entries.values():
        chosen = [
            RunScenario(
                scenario_id=scenario.scenario_id,
                persona_ids=personas[scenario.id],
                data_set_ids=scenario.data_set_ids,
                answered_by=scenario.answered_by,
            )
            for scenario in scenarios[entry.id].values()
        ]
        found[entry.suite_id].append(
            SuiteEntry(
                agent_id=entry.agent_id,
                transport=entry.transport,
                scenarios=(
                    AllScenarios(answered_by=entry.all_scenarios_answered_by)
                    if entry.all_scenarios_answered_by is not None
                    else chosen
                ),
                repeats=entry.repeats,
                max_duration_s=entry.max_duration_s,
                max_turns=entry.max_turns,
                max_parallel=entry.max_parallel,
                start_interval_s=entry.start_interval_s,
                max_retries=entry.max_retries,
            )
        )
    return found


async def check_entries(session: AsyncSession, entries: Sequence[SuiteEntry]) -> list[EntryCheck]:
    """Each entry as it would start now. The calls of a scenario are its personas times its
    data sets times its answers times the repeats."""
    agents = {
        row.id: row
        for row in await session.scalars(
            select(Agent).where(Agent.id.in_({entry.agent_id for entry in entries}))
        )
    }
    every = await live_scenarios(
        session,
        {entry.agent_id for entry in entries if isinstance(entry.scenarios, AllScenarios)},
    )
    scenarios = {
        row.id: row
        for row in await session.scalars(
            select(Scenario).where(
                Scenario.id.in_(
                    {item.scenario_id for entry in entries for item in chosen_scenarios(entry)}
                )
            )
        )
    }
    personas = {
        row.id: row
        for row in await session.scalars(
            select(Persona).where(
                Persona.id.in_(
                    {
                        persona_id
                        for entry in entries
                        for item in chosen_scenarios(entry)
                        for persona_id in item.persona_ids or []
                    }
                )
            )
        )
    }
    return [
        entry_check(entry, agents[entry.agent_id], every, scenarios, personas) for entry in entries
    ]


def entry_check(
    entry: SuiteEntry,
    agent: Agent,
    every: dict[uuid.UUID, list[Scenario]],
    scenarios: dict[uuid.UUID, Scenario],
    personas: dict[uuid.UUID, Persona],
) -> EntryCheck:
    problems = []
    try:
        chosen_transport(agent_config_of(agent).transports, entry.transport)
    except ValidationError as error:
        problems.append(str(error))
    if isinstance(entry.scenarios, AllScenarios):
        answers = [entry.scenarios.answered_by]
        found = every.get(agent.id, [])
        if not found:
            problems.append("the agent has no scenarios")
        calls = sum(
            len(scenario_config_of(scenario).data_sets) * len(entry.scenarios.answered_by)
            for scenario in found
        )
        count = len(found)
    else:
        answers = [item.answered_by for item in entry.scenarios]
        calls = 0
        count = 0
        for item in entry.scenarios:
            scenario = scenarios[item.scenario_id]
            if scenario.deleted_at is not None:
                problems.append(f'the scenario "{scenario.name}" was deleted')
                continue
            data_sets = {data_set.id for data_set in scenario_config_of(scenario).data_sets}
            if not set(item.data_set_ids or []) <= data_sets:
                problems.append(f'the scenario "{scenario.name}" no longer has a chosen data set')
            for persona_id in item.persona_ids or []:
                persona = personas[persona_id]
                if persona.deleted_at is not None:
                    problems.append(f'the persona "{persona.name}" was deleted')
            calls += (
                len(item.persona_ids or [None])
                * len(item.data_set_ids or data_sets)
                * len(item.answered_by)
            )
            count += 1
    machines = any(answer is not AnsweredBy.CALLER for listed in answers for answer in listed)
    if machines and not machines_answer(entry.transport, agent.direction):
        problems.append("voicemail and call screening need a phone run of an outbound agent")
    if agent.deleted_at is not None:
        problems = ["the agent was deleted"]
    return EntryCheck(
        agent_name=agent.name,
        scenarios=count,
        calls=calls * entry.repeats,
        problems=list(dict.fromkeys(problems)),
    )


async def live_scenarios(
    session: AsyncSession, agent_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[Scenario]]:
    """The live scenarios of these agents, in the order the agent's scenario list shows them."""
    rows = await session.scalars(
        select(Scenario)
        .where(Scenario.agent_id.in_(set(agent_ids)), Scenario.deleted_at.is_(None))
        .order_by(Scenario.created_at.desc(), Scenario.id)
    )
    found: dict[uuid.UUID, list[Scenario]] = defaultdict(list)
    for row in rows:
        found[row.agent_id].append(row)
    return found


def entry_label(position: int, agent_name: str, entry: SuiteEntry) -> str:
    return f"entry {position}, {agent_name} ({entry.transport.value})"


async def start_suite(
    session: AsyncSession,
    settings: Settings,
    app: AppSettings,
    suite_id: uuid.UUID,
    request_key: str | None,
    check_caller: CallerCheck | None = None,
) -> SuiteRun:
    """Start one run for each entry, all of them or none. Every entry is checked, and one
    refusal names each entry and its problem. Starts of one suite wait for each other at the
    suite's lock, so the key is looked up again under it: a request that waited for another
    one with its key returns that suite run, even if the suite changed since."""
    earlier = await earlier_suite_run(session, suite_id, request_key)
    if earlier is not None:
        return earlier
    suite = await session.get(Suite, suite_id, with_for_update=True, populate_existing=True)
    earlier = await earlier_suite_run(session, suite_id, request_key)
    if earlier is not None:
        await session.commit()
        return earlier
    if suite is None or suite.deleted_at is not None:
        raise NotFoundError("suite not found")
    entries = (await saved_entries(session, [suite.id]))[suite.id]
    if not entries:
        raise ValidationError("the suite has no agents: add one before a start")
    agents = {
        row.id: row
        for row in await session.scalars(
            select(Agent)
            .where(Agent.id.in_({entry.agent_id for entry in entries}))
            .order_by(Agent.id)
            .with_for_update()
        )
    }
    every = await live_scenarios(
        session,
        {entry.agent_id for entry in entries if isinstance(entry.scenarios, AllScenarios)},
    )
    wanted = [
        [
            RunScenario(scenario_id=scenario.id, answered_by=entry.scenarios.answered_by)
            for scenario in every.get(entry.agent_id, [])
        ]
        if isinstance(entry.scenarios, AllScenarios)
        else entry.scenarios
        for entry in entries
    ]
    await share_lock_references(session, wanted)
    checks = await check_entries(session, entries)
    problems: list[str] = []
    prepared: list[tuple[str, PreparedRun]] = []
    for position, (entry, scenarios, check) in enumerate(
        zip(entries, wanted, checks, strict=True), 1
    ):
        label = entry_label(position, check.agent_name, entry)
        if check.problems:
            problems += [f"{label}: {problem}" for problem in check.problems]
            continue
        try:
            run = await prepare_run(
                session,
                settings,
                app,
                agents[entry.agent_id],
                entry.run_create(scenarios, suite.name),
            )
        except (NotFoundError, ValidationError) as error:
            problems.append(f"{label}: {error}")
            continue
        prepared.append((label, run))
    if check_caller is not None and prepared:
        refused = await unserved_callers(
            session, check_caller, [item for _, run in prepared for item in run.inputs]
        )
        for label, run in prepared:
            versions = {item.scenario_version_id for item in run.inputs}
            problems += [
                f"{label}: {caller.message(versions)}"
                for caller in refused
                if versions & caller.chosen_by.keys()
            ]
    if problems:
        raise ValidationError("; ".join(problems))
    suite_run = SuiteRun(
        suite_id=suite.id,
        required_pass_percent=suite.required_pass_percent,
        request_key=request_key,
    )
    session.add(suite_run)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        if REQUEST_KEY_INDEX not in str(error.orig):
            raise
        earlier = await earlier_suite_run(session, suite_id, request_key)
        assert earlier is not None
        return earlier
    for position, (_, run) in enumerate(prepared, 1):
        await add_run(session, run, suite_run_id=suite_run.id, suite_position=position)
    await session.commit()
    return suite_run


async def share_lock_references(
    session: AsyncSession, wanted: Sequence[Sequence[RunScenario]]
) -> None:
    """Share-lock every scenario of the start, then every persona it plays, each set in id
    order, before any entry's snapshot locks its own: entry by entry, a scenario edit, which
    locks a scenario and then a persona, could deadlock with the start. The rows are read again
    under the locks, so an edit that committed while the start waited is what it plays."""
    scenarios = await session.scalars(
        select(Scenario)
        .where(Scenario.id.in_({item.scenario_id for items in wanted for item in items}))
        .order_by(Scenario.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    own = {scenario.id: scenario.persona_id for scenario in scenarios}
    persona_ids = {
        persona_id
        for items in wanted
        for item in items
        for persona_id in item.persona_ids or [own.get(item.scenario_id)]
        if persona_id is not None
    }
    await session.execute(
        select(Persona)
        .where(Persona.id.in_(persona_ids))
        .order_by(Persona.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )


async def earlier_suite_run(
    session: AsyncSession, suite_id: uuid.UUID, request_key: str | None
) -> SuiteRun | None:
    """The suite run that an earlier start with this idempotency key made. The request is only
    the suite, so the key with another suite is refused."""
    if request_key is None:
        return None
    found = await session.scalar(select(SuiteRun).where(SuiteRun.request_key == request_key))
    if found is not None and found.suite_id != suite_id:
        raise ConflictError("the Idempotency-Key was already used for another suite")
    return found


async def get_suite_run(session: AsyncSession, suite_run_id: uuid.UUID) -> SuiteRun:
    suite_run = await session.get(SuiteRun, suite_run_id)
    if suite_run is None:
        raise NotFoundError("suite run not found")
    return suite_run


async def list_suite_runs(
    session: AsyncSession, suite_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[list[SuiteRun], int]:
    query = select(SuiteRun).where(SuiteRun.suite_id == suite_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(SuiteRun.created_at.desc(), SuiteRun.id.desc()).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def last_suite_runs(
    session: AsyncSession, suite_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, SuiteRun]:
    rows = await session.scalars(
        select(SuiteRun)
        .where(SuiteRun.suite_id.in_(suite_ids))
        .distinct(SuiteRun.suite_id)
        .order_by(SuiteRun.suite_id, SuiteRun.created_at.desc(), SuiteRun.id.desc())
    )
    return {row.suite_id: row for row in rows}


async def runs_of(
    session: AsyncSession, suite_run_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[Run]]:
    """Each suite run's runs, in entry order."""
    rows = await session.scalars(
        select(Run)
        .where(Run.suite_run_id.in_(suite_run_ids))
        .order_by(Run.suite_run_id, Run.suite_position)
    )
    found: dict[uuid.UUID, list[Run]] = {suite_run_id: [] for suite_run_id in suite_run_ids}
    for row in rows:
        assert row.suite_run_id is not None
        found[row.suite_run_id].append(row)
    return found


async def suite_names(
    session: AsyncSession, suite_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    rows = await session.execute(select(Suite.id, Suite.name).where(Suite.id.in_(set(suite_ids))))
    return dict(rows.tuples().all())


async def cancel_suite_run(session: AsyncSession, suite_run_id: uuid.UUID) -> SuiteRun:
    """Cancel every run of the suite run in one transaction: the suite run first, then its runs
    in id order. A suite run with no run at work stays as it is."""
    suite_run = await session.get(
        SuiteRun, suite_run_id, with_for_update=True, populate_existing=True
    )
    if suite_run is None:
        raise NotFoundError("suite run not found")
    runs = await session.scalars(
        select(Run)
        .where(Run.suite_run_id == suite_run.id)
        .order_by(Run.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    active = [await cancel_conversations(session, run) for run in runs]
    if any(active) and suite_run.cancelled_at is None:
        suite_run.cancelled_at = func.statement_timestamp()
    await session.commit()
    await session.refresh(suite_run)
    return suite_run


async def suite_links(session: AsyncSession, runs: Sequence[Run]) -> dict[uuid.UUID, SuiteRunLink]:
    """The suite run of each run that a suite started."""
    started = [run for run in runs if run.suite_run_id is not None]
    rows = await session.execute(
        select(SuiteRun.id, SuiteRun.suite_id, Suite.name)
        .join(Suite, Suite.id == SuiteRun.suite_id)
        .where(SuiteRun.id.in_({run.suite_run_id for run in started}))
    )
    found: dict[uuid.UUID, Row[Any]] = {row.id: row for row in rows}
    links = {}
    for run in started:
        assert run.suite_run_id is not None and run.suite_position is not None
        row = found[run.suite_run_id]
        links[run.id] = SuiteRunLink(
            id=row.id, suite_id=row.suite_id, suite_name=row.name, position=run.suite_position
        )
    return links
