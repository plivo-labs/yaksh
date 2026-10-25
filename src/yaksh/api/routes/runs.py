import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.api.auth import require_token
from yaksh.api.deps import AppSettingsDep, SessionDep, SettingsDep
from yaksh.api.pagination import Page, PageDep
from yaksh.api.schemas.runs import RunRead, RunSummary
from yaksh.db.models import Run
from yaksh.domain.agents import Transport
from yaksh.domain.evaluations import RunMetrics
from yaksh.domain.latency import pooled
from yaksh.domain.runs import RunCreate, RunStatus
from yaksh.domain.settings import AppSettings, CallerModel
from yaksh.evaluation import results
from yaksh.integrations import provider_checks
from yaksh.integrations.openai_models import caller_effort
from yaksh.simulation import conversations, runs, suites

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_token)])


async def summaries(session: AsyncSession, rows: list[Run]) -> list[RunSummary]:
    agents = await conversations.pinned_agents(session, (row.agent_version_id for row in rows))
    progress = await runs.progress(session, rows)
    languages = await runs.caller_languages(session, [row.id for row in rows])
    counted = await runs.counted_conversations(session, [row.id for row in rows])
    found = await results.evaluated(session, (c for ids in counted.values() for c in ids))
    measured = {key: done.latency for key, done in found.items() if done.latency}
    links = await suites.suite_links(session, rows)
    return [
        RunSummary.of(
            row,
            agents[row.agent_version_id],
            progress[row.id],
            pooled([measured[c] for c in counted.get(row.id, []) if c in measured]),
            languages.get(row.id, []),
            links.get(row.id),
        )
        for row in rows
    ]


async def detail(session: AsyncSession, run: Run) -> RunRead:
    base = (await summaries(session, [run]))[0]
    return RunRead(
        **base.model_dump(),
        scenarios=await runs.run_scenarios(session, run),
    )


def caller_check(app: AppSettings) -> runs.CallerCheck | None:
    """One short answer from a caller model with its effort; None without an LLM key, when the
    run's own checks refuse the run."""
    key = app.secrets.llm_api_key
    if key is None:
        return None

    async def check(caller: CallerModel) -> str | None:
        try:
            await provider_checks.check_llm(
                app.llm.base_url,
                key.get_secret_value(),
                caller.model,
                caller_effort(caller.model, caller.reasoning_effort),
            )
        except provider_checks.ProviderCheckError as error:
            return str(error)
        return None

    return check


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    command: RunCreate,
    session: SessionDep,
    settings: SettingsDep,
    app: AppSettingsDep,
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None,
) -> RunSummary:
    run = await runs.create_run(session, settings, app, command, idempotency_key, caller_check(app))
    return (await summaries(session, [run]))[0]


@router.get("")
async def list_runs(
    session: SessionDep,
    page: PageDep,
    agent_id: uuid.UUID | None = None,
    transport: Transport | None = None,
    status: RunStatus | None = None,
    created_from: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
    suite_id: uuid.UUID | None = None,
) -> Page[RunSummary]:
    """`created_from` includes its time and `created_before` excludes its time, so ranges
    next to each other do not overlap. Both need a time zone."""
    rows, total = await runs.list_runs(
        session,
        offset=page.offset,
        limit=page.page_size,
        agent_id=agent_id,
        transport=transport,
        status=status,
        created_from=created_from,
        created_before=created_before,
        suite_id=suite_id,
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
        [scenario.scenario_id for scenario in await runs.run_scenarios(session, run)],
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
