import uuid

from fastapi import APIRouter, Depends, status

from truman.api.auth import require_token
from truman.api.deps import SessionDep
from truman.api.pagination import Page, PageDep
from truman.api.schemas.scenarios import ScenarioRead, ScenarioVersionRead
from truman.domain.scenarios import ScenarioCreate, ScenarioUpdate
from truman.simulation import scenarios

router = APIRouter(tags=["scenarios"], dependencies=[Depends(require_token)])


@router.post("/agents/{agent_id}/scenarios", status_code=status.HTTP_201_CREATED)
async def create_scenario(
    agent_id: uuid.UUID, command: ScenarioCreate, session: SessionDep
) -> ScenarioRead:
    return ScenarioRead.of(await scenarios.create_scenario(session, agent_id, command))


@router.get("/agents/{agent_id}/scenarios")
async def list_scenarios(
    agent_id: uuid.UUID, session: SessionDep, page: PageDep
) -> Page[ScenarioRead]:
    rows, total = await scenarios.list_scenarios(
        session, agent_id, offset=page.offset, limit=page.page_size
    )
    return Page.of([ScenarioRead.of(row) for row in rows], total, page)


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
