import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from truman.api.auth import require_token
from truman.api.deps import SessionDep, SettingsDep
from truman.api.pagination import Page, PageDep
from truman.api.schemas.runs import RunRead, RunSummary
from truman.db.models import Run
from truman.domain.evaluations import RunMetrics
from truman.domain.latency import pooled
from truman.domain.runs import RunCreate, RunStatus
from truman.evaluation import results
from truman.simulation import conversations, runs

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_token)])


async def summaries(session: AsyncSession, rows: list[Run]) -> list[RunSummary]:
    agents = await conversations.pinned_agents(session, (row.agent_version_id for row in rows))
    progress = await runs.progress(session, rows)
    counted = await runs.counted_conversations(session, [row.id for row in rows])
    found = await results.evaluated(session, (c for ids in counted.values() for c in ids))
    measured = {key: done.latency for key, done in found.items() if done.latency}
    return [
        RunSummary.of(
            row,
            agents[row.agent_version_id],
            progress[row.id],
            pooled([measured[c] for c in counted.get(row.id, []) if c in measured]),
        )
        for row in rows
    ]


async def detail(session: AsyncSession, run: Run) -> RunRead:
    base = (await summaries(session, [run]))[0]
    return RunRead(**base.model_dump(), scenario_ids=await runs.scenario_ids(session, run))


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    command: RunCreate,
    session: SessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None,
) -> RunSummary:
    run = await runs.create_run(session, settings, command, idempotency_key)
    return (await summaries(session, [run]))[0]


@router.get("")
async def list_runs(
    session: SessionDep,
    page: PageDep,
    agent_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
) -> Page[RunSummary]:
    rows, total = await runs.list_runs(
        session, offset=page.offset, limit=page.page_size, agent_id=agent_id, status=status
    )
    return Page.of(await summaries(session, rows), total, page)


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, session: SessionDep) -> RunRead:
    return await detail(session, await runs.get_run(session, run_id))


@router.get("/{run_id}/metrics")
async def get_run_metrics(run_id: uuid.UUID, session: SessionDep) -> RunMetrics:
    """The numbers over the run's counted conversations: the latest attempt of each repeat,
    unless it was cancelled."""
    run = await runs.get_run(session, run_id)
    counted = await runs.counted_conversations(session, [run.id])
    return await results.run_metrics(
        session,
        counted.get(run.id, []),
        await runs.scenario_ids(session, run),
        seed=run.id.int,
    )


@router.post(
    "/{run_id}/cancel",
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": RunRead,
            "description": "The run is cancelled, and some of its calls are still stopping.",
        }
    },
)
async def cancel_run(run_id: uuid.UUID, session: SessionDep, response: Response) -> RunRead:
    cancelled = await detail(session, await runs.cancel_run(session, run_id))
    if cancelled.status is RunStatus.CANCELLING:
        response.status_code = status.HTTP_202_ACCEPTED
    return cancelled
