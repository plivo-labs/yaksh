import uuid
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from yaksha.api.auth import require_token
from yaksha.api.deps import AppSettingsDep, BriefModelDep, GenerationModelDep
from yaksha.api.errors import CLIENT_ERRORS, UNAVAILABLE, json_errors
from yaksha.domain.errors import UnavailableError
from yaksha.domain.forks import ForkRequest, ScenarioForkRequest
from yaksha.domain.personas import PersonaCreate
from yaksha.domain.scenarios import DataSet, ScenarioCreate
from yaksha.simulation import data_set_drafts, forks

router = APIRouter(tags=["forks"], dependencies=[Depends(require_token)])


async def stream[T: BaseModel](
    events: AsyncGenerator[forks.Event[T]], item: str = "fork"
) -> AsyncIterator[ServerSentEvent]:
    """`planned` with how many drafts the instruction has room for, then an `item` event for
    each draft or `dropped` with why one could not be written, or `failed` when the plan itself
    failed."""
    try:
        async for event in events:
            match event:
                case forks.Planned(count):
                    yield ServerSentEvent(data={"count": count}, event="planned")
                case forks.Drafted(draft):
                    yield ServerSentEvent(data=draft.model_dump(mode="json"), event=item)
                case forks.Dropped(reason):
                    yield ServerSentEvent(data={"reason": reason}, event="dropped")
    except UnavailableError as error:
        yield ServerSentEvent(data={"error": str(error)}, event="failed")


async def scenario_events(
    scenario_id: uuid.UUID, fork: ScenarioForkRequest, request: Request, model: GenerationModelDep
) -> AsyncIterator[AsyncGenerator[forks.Event[ScenarioCreate]]]:
    """The source is read in a short session before the stream opens, so a refusal is an
    ordinary error and no connection is held while the model writes. The writers are closed
    here after the stream ends: FastAPI does not close the endpoint when the console
    disconnects while an event waits to be sent."""
    async with request.app.state.sessionmaker() as session:
        source = await forks.scenario_source(session, model, scenario_id)
    assert model is not None
    events = forks.scenario_forks(model, source, fork)
    try:
        yield events
    finally:
        with anyio.CancelScope(shield=True):
            await events.aclose()


async def data_set_events(
    scenario_id: uuid.UUID,
    command: ForkRequest,
    request: Request,
    model: GenerationModelDep,
    app: AppSettingsDep,
) -> AsyncIterator[AsyncGenerator[forks.Event[DataSet]]]:
    """As scenario_events, for new data sets of a scenario; a request for more data sets than
    the scenario has room for is refused before the stream opens."""
    async with request.app.state.sessionmaker() as session:
        source = await forks.scenario_source(session, model, scenario_id)
    data_set_drafts.check_room(app.limits, source, command)
    assert model is not None
    events = data_set_drafts.data_set_drafts(model, source, command)
    try:
        yield events
    finally:
        with anyio.CancelScope(shield=True):
            await events.aclose()


async def persona_events(
    persona_id: uuid.UUID, fork: ForkRequest, request: Request, model: BriefModelDep
) -> AsyncIterator[AsyncGenerator[forks.Event[PersonaCreate]]]:
    """As scenario_events, for a persona."""
    async with request.app.state.sessionmaker() as session:
        source = await forks.persona_source(session, model, persona_id)
    assert model is not None
    events = forks.persona_forks(model, source, fork)
    try:
        yield events
    finally:
        with anyio.CancelScope(shield=True):
            await events.aclose()


@router.post(
    "/scenarios/{scenario_id}/forks/draft",
    response_class=EventSourceResponse,
    responses=json_errors({**CLIENT_ERRORS, **UNAVAILABLE}),
)
async def draft_scenario_forks(
    events: Annotated[
        AsyncGenerator[forks.Event[ScenarioCreate]], Depends(scenario_events, scope="request")
    ],
) -> AsyncIterable[ServerSentEvent]:
    """Writes forks of the scenario, each a scenario the console can create with its
    forked_from_id. Nothing is saved."""
    async for event in stream(events):
        yield event


@router.post(
    "/scenarios/{scenario_id}/data-sets/draft",
    response_class=EventSourceResponse,
    responses=json_errors({**CLIENT_ERRORS, **UNAVAILABLE}),
)
async def draft_data_sets(
    events: Annotated[
        AsyncGenerator[forks.Event[DataSet]], Depends(data_set_events, scope="request")
    ],
) -> AsyncIterable[ServerSentEvent]:
    """Writes new data sets for the scenario: `planned`, then `data_set` for each one, which
    the console adds to the scenario with an update. Nothing is saved."""
    async for event in stream(events, item="data_set"):
        yield event


@router.post(
    "/personas/{persona_id}/forks/draft",
    response_class=EventSourceResponse,
    responses=json_errors({**CLIENT_ERRORS, **UNAVAILABLE}),
)
async def draft_persona_forks(
    events: Annotated[
        AsyncGenerator[forks.Event[PersonaCreate]], Depends(persona_events, scope="request")
    ],
) -> AsyncIterable[ServerSentEvent]:
    """Writes forks of the persona, each a persona the console can create with its
    forked_from_id. Nothing is saved."""
    async for event in stream(events):
        yield event
