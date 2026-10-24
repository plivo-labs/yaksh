import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.api.auth import require_token
from yaksh.api.deps import AppSettingsDep, SessionDep, SettingsDep
from yaksh.api.pagination import Page, PageDep
from yaksh.api.routes.runs import caller_check, summaries
from yaksh.api.schemas.suites import (
    SuiteEntryRead,
    SuiteRead,
    SuiteRunPart,
    SuiteRunRead,
    SuiteRunSummary,
    SuiteSummary,
)
from yaksh.db.models import Run, Suite, SuiteRun
from yaksh.domain.evaluations import GateNumbers
from yaksh.domain.runs import RunProgress, RunStatus
from yaksh.domain.suites import RunResult, SuiteCreate, SuiteUpdate, run_result, suite_result
from yaksh.evaluation import gates
from yaksh.simulation import runs, suites

router = APIRouter(prefix="/suites", tags=["suites"], dependencies=[Depends(require_token)])
run_router = APIRouter(prefix="/suite-runs", tags=["suites"], dependencies=[Depends(require_token)])

ENDED = frozenset({RunStatus.DONE, RunStatus.CANCELLED})


@dataclass(frozen=True)
class Judged:
    """A run of a suite run, with what its result is read from."""

    run: Run
    progress: RunProgress
    numbers: GateNumbers
    result: RunResult


async def judged_runs(
    session: AsyncSession, suite_runs: Sequence[SuiteRun]
) -> dict[uuid.UUID, list[Judged]]:
    """The runs of each suite run, in entry order, each with its result against the pass rate
    that the suite run copied."""
    by_suite_run = await suites.runs_of(session, [suite_run.id for suite_run in suite_runs])
    every = [run for found in by_suite_run.values() for run in found]
    progress = await runs.progress(session, every)
    counted = await runs.counted_conversations(session, [run.id for run in every], stopped=True)
    numbers = await gates.gate_numbers(session, {run.id: counted.get(run.id, []) for run in every})
    percent = {suite_run.id: suite_run.required_pass_percent for suite_run in suite_runs}
    return {
        suite_run_id: [
            Judged(
                run,
                progress[run.id],
                numbers[run.id],
                run_result(progress[run.id].status, numbers[run.id], percent[suite_run_id]),
            )
            for run in found
        ]
        for suite_run_id, found in by_suite_run.items()
    }


def summary_of(suite_run: SuiteRun, suite_name: str, parts: Sequence[Judged]) -> SuiteRunSummary:
    ended = [part.progress.ended_at for part in parts if part.progress.status in ENDED]
    return SuiteRunSummary(
        id=suite_run.id,
        suite_id=suite_run.suite_id,
        suite_name=suite_name,
        required_pass_percent=suite_run.required_pass_percent,
        result=suite_result([part.result for part in parts]),
        created_at=suite_run.created_at,
        ended_at=max(filter(None, ended), default=None) if len(ended) == len(parts) else None,
        cancelled_at=suite_run.cancelled_at,
        run_count=len(parts),
        passed_run_count=sum(part.result is RunResult.PASSED for part in parts),
        conversation_count=sum(sum(part.progress.counts.values()) for part in parts),
    )


async def suite_run_summaries(
    session: AsyncSession, suite_runs: Sequence[SuiteRun]
) -> list[SuiteRunSummary]:
    judged = await judged_runs(session, suite_runs)
    names = await suites.suite_names(session, {suite_run.suite_id for suite_run in suite_runs})
    return [
        summary_of(suite_run, names[suite_run.suite_id], judged[suite_run.id])
        for suite_run in suite_runs
    ]


async def suite_run_detail(session: AsyncSession, suite_run: SuiteRun) -> SuiteRunRead:
    parts = (await judged_runs(session, [suite_run]))[suite_run.id]
    names = await suites.suite_names(session, [suite_run.suite_id])
    shown = await summaries(session, [part.run for part in parts])
    return SuiteRunRead(
        **summary_of(suite_run, names[suite_run.suite_id], parts).model_dump(),
        runs=[
            SuiteRunPart(run=run, result=part.result, numbers=part.numbers)
            for run, part in zip(shown, parts, strict=True)
        ],
    )


async def suite_reads(session: AsyncSession, rows: Sequence[Suite]) -> list[SuiteRead]:
    entries = await suites.saved_entries(session, [row.id for row in rows])
    flat = [(row.id, entry) for row in rows for entry in entries[row.id]]
    checks = await suites.check_entries(session, [entry for _, entry in flat])
    reads: dict[uuid.UUID, list[SuiteEntryRead]] = {row.id: [] for row in rows}
    for (suite_id, entry), check in zip(flat, checks, strict=True):
        reads[suite_id].append(
            SuiteEntryRead(
                **entry.model_dump(),
                position=len(reads[suite_id]) + 1,
                agent_name=check.agent_name,
                scenario_count=check.scenarios,
                calls=check.calls,
                problems=check.problems,
            )
        )
    last = await suites.last_suite_runs(session, [row.id for row in rows])
    last_runs = {
        summary.suite_id: summary
        for summary in await suite_run_summaries(session, list(last.values()))
    }
    found = []
    for row in rows:
        read = reads[row.id]
        found.append(
            SuiteRead(
                id=row.id,
                name=row.name,
                required_pass_percent=row.required_pass_percent,
                revision=row.revision,
                created_at=row.created_at,
                updated_at=row.updated_at,
                agent_names=list(dict.fromkeys(entry.agent_name for entry in read)),
                calls=sum(entry.calls for entry in read),
                last_run=last_runs.get(row.id),
                entries=read,
            )
        )
    return found


async def suite_read(session: AsyncSession, suite: Suite) -> SuiteRead:
    return (await suite_reads(session, [suite]))[0]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_suite(command: SuiteCreate, session: SessionDep) -> SuiteRead:
    return await suite_read(session, await suites.create_suite(session, command))


@router.get("")
async def list_suites(session: SessionDep, page: PageDep) -> Page[SuiteSummary]:
    rows, total = await suites.list_suites(session, offset=page.offset, limit=page.page_size)
    found = await suite_reads(session, rows)
    return Page.of(
        [SuiteSummary(**read.model_dump(exclude={"entries"})) for read in found], total, page
    )


@router.get("/{suite_id}")
async def get_suite(suite_id: uuid.UUID, session: SessionDep) -> SuiteRead:
    return await suite_read(session, await suites.get_suite(session, suite_id))


@router.patch("/{suite_id}")
async def update_suite(
    suite_id: uuid.UUID, update: SuiteUpdate, session: SessionDep, app: AppSettingsDep
) -> SuiteRead:
    suite = await suites.update_suite(session, suite_id, update, app.limits)
    return await suite_read(session, suite)


@router.delete("/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(suite_id: uuid.UUID, session: SessionDep) -> None:
    await suites.delete_suite(session, suite_id)


@router.post("/{suite_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_suite(
    suite_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    app: AppSettingsDep,
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None,
) -> SuiteRunRead:
    """Starts one run for each entry, all of them or none. A refusal names each entry and its
    problem."""
    suite_run = await suites.start_suite(
        session, settings, app, suite_id, idempotency_key, caller_check(app)
    )
    return await suite_run_detail(session, suite_run)


@router.get("/{suite_id}/runs")
async def list_suite_runs(
    suite_id: uuid.UUID, session: SessionDep, page: PageDep
) -> Page[SuiteRunSummary]:
    rows, total = await suites.list_suite_runs(
        session, suite_id, offset=page.offset, limit=page.page_size
    )
    return Page.of(await suite_run_summaries(session, rows), total, page)


@run_router.get("/{suite_run_id}")
async def get_suite_run(suite_run_id: uuid.UUID, session: SessionDep) -> SuiteRunRead:
    return await suite_run_detail(session, await suites.get_suite_run(session, suite_run_id))


@run_router.post(
    "/{suite_run_id}/cancel",
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": SuiteRunRead,
            "description": "The suite run is cancelled, and some of its calls are still stopping.",
        }
    },
)
async def cancel_suite_run(
    suite_run_id: uuid.UUID, session: SessionDep, response: Response
) -> SuiteRunRead:
    cancelled = await suite_run_detail(
        session, await suites.cancel_suite_run(session, suite_run_id)
    )
    if any(part.run.status is RunStatus.CANCELLING for part in cancelled.runs):
        response.status_code = status.HTTP_202_ACCEPTED
    return cancelled
