import uuid
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from truman.api.auth import require_token
from truman.api.deps import SessionDep
from truman.api.pagination import Page, PageDep
from truman.api.schemas.scenarios import GenerationRead, ScenarioRead, ScenarioVersionRead
from truman.domain.generation import GenerateScenarios
from truman.domain.scenarios import ScenarioCreate, ScenarioDelete, ScenarioUpdate
from truman.simulation import generation, scenarios

router = APIRouter(tags=["scenarios"], dependencies=[Depends(require_token)])


@router.post("/agents/{agent_id}/scenarios", status_code=status.HTTP_201_CREATED)
async def create_scenario(
    agent_id: uuid.UUID, command: ScenarioCreate, session: SessionDep
) -> ScenarioRead:
    return ScenarioRead.of(await scenarios.create_scenario(session, agent_id, command))


async def prepared_generation(
    agent_id: uuid.UUID, command: GenerateScenarios, request: Request
) -> generation.Prepared:
    """Checks the request before the stream opens, so a refusal is an ordinary error."""
    async with request.app.state.sessionmaker() as session:
        return await generation.prepare(
            session, request.app.state.generation_model, agent_id, command
        )


def event_data(event: generation.Event) -> tuple[str, dict[str, Any]]:
    match event:
        case generation.Started(generation_id):
            return "started", {"generation_id": str(generation_id)}
        case generation.Planned(count):
            return "planned", {"count": count}
        case generation.Saved(scenario):
            return "scenario", ScenarioRead.of(scenario).model_dump(mode="json")
        case generation.Dropped(reason):
            return "dropped", {"reason": reason}
        case generation.Finished(status_, saved, dropped, error):
            return "finished", {
                "status": status_.value,
                "saved": saved,
                "dropped": dropped,
                "error": error,
            }


async def generation_events(
    prepared: Annotated[generation.Prepared, Depends(prepared_generation)], request: Request
) -> AsyncIterator[AsyncGenerator[generation.Event]]:
    """Closes the generation after the stream ends. FastAPI does not close the endpoint when
    the console disconnects while an event waits to be sent, so the endpoint cannot."""
    events = generation.generate(
        request.app.state.sessionmaker, request.app.state.generation_model, prepared
    )
    try:
        yield events
    finally:
        with anyio.CancelScope(shield=True):
            await events.aclose()


@router.post("/agents/{agent_id}/scenarios/generate", response_class=EventSourceResponse)
async def generate_scenarios(
    events: Annotated[
        AsyncGenerator[generation.Event], Depends(generation_events, scope="request")
    ],
) -> AsyncIterable[ServerSentEvent]:
    """Writes scenarios and streams each one as it is saved. Closing the stream stops the
    generation; what is saved stays."""
    async for event in events:
        name, data = event_data(event)
        yield ServerSentEvent(data=data, event=name)


@router.get("/agents/{agent_id}/scenarios")
async def list_scenarios(
    agent_id: uuid.UUID,
    session: SessionDep,
    page: PageDep,
    generation_id: uuid.UUID | None = None,
) -> Page[ScenarioRead]:
    rows, total = await scenarios.list_scenarios(
        session, agent_id, offset=page.offset, limit=page.page_size, generation_id=generation_id
    )
    return Page.of([ScenarioRead.of(row) for row in rows], total, page)


@router.post("/agents/{agent_id}/scenarios/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenarios(
    agent_id: uuid.UUID, command: ScenarioDelete, session: SessionDep
) -> None:
    await scenarios.delete_scenarios(session, agent_id, command)


@router.get("/agents/{agent_id}/scenario-generations")
async def list_generations(
    agent_id: uuid.UUID, session: SessionDep, page: PageDep
) -> Page[GenerationRead]:
    rows, total = await generation.list_generations(
        session, agent_id, offset=page.offset, limit=page.page_size
    )
    return Page.of([GenerationRead.of(row, count) for row, count in rows], total, page)


@router.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: uuid.UUID, session: SessionDep) -> ScenarioRead:
    return ScenarioRead.of(await scenarios.get_scenario(session, scenario_id))


@router.patch("/scenarios/{scenario_id}")
async def update_scenario(
    scenario_id: uuid.UUID, update: ScenarioUpdate, session: SessionDep
) -> ScenarioRead:
    return ScenarioRead.of(await scenarios.update_scenario(session, scenario_id, update))


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(scenario_id: uuid.UUID, session: SessionDep) -> None:
    await scenarios.delete_scenario(session, scenario_id)


@router.get("/scenarios/{scenario_id}/versions")
async def list_versions(
    scenario_id: uuid.UUID, session: SessionDep, page: PageDep
) -> Page[ScenarioVersionRead]:
    rows, total = await scenarios.list_versions(
        session, scenario_id, offset=page.offset, limit=page.page_size
    )
    return Page.of([ScenarioVersionRead.model_validate(row) for row in rows], total, page)


@router.get("/scenarios/{scenario_id}/versions/{version}")
async def get_version(
    scenario_id: uuid.UUID, version: int, session: SessionDep
) -> ScenarioVersionRead:
    return ScenarioVersionRead.model_validate(
        await scenarios.get_version(session, scenario_id, version)
    )
