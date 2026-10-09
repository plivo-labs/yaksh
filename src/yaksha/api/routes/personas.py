import uuid

from fastapi import APIRouter, Depends, status

from yaksha.api.auth import require_token
from yaksha.api.deps import BriefModelDep, SessionDep
from yaksha.api.errors import UNAVAILABLE
from yaksha.api.pagination import Page, PageDep
from yaksha.api.schemas.personas import PersonaRead, PersonaScenario, PersonaVersionRead
from yaksha.domain.personas import PersonaCreate, PersonaDraft, PersonaIdea, PersonaUpdate
from yaksha.simulation import personas
from yaksha.simulation.persona_drafts import draft_persona

router = APIRouter(prefix="/personas", tags=["personas"], dependencies=[Depends(require_token)])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_persona(command: PersonaCreate, session: SessionDep) -> PersonaRead:
    return PersonaRead.of(await personas.create_persona(session, command))


@router.post("/draft", responses=UNAVAILABLE)
async def draft_new_persona(
    source: PersonaIdea, model: BriefModelDep, session: SessionDep
) -> PersonaDraft:
    """Write a new persona's fields from a short line. Nothing is saved."""
    return await draft_persona(model, source, await personas.persona_names(session))


@router.get("")
async def list_personas(session: SessionDep, page: PageDep) -> Page[PersonaRead]:
    rows, total = await personas.list_personas(session, offset=page.offset, limit=page.page_size)
    return Page.of([PersonaRead.of(row) for row in rows], total, page)


@router.get("/{persona_id}")
async def get_persona(persona_id: uuid.UUID, session: SessionDep) -> PersonaRead:
    return PersonaRead.of(await personas.get_persona(session, persona_id))


@router.patch("/{persona_id}")
async def update_persona(
    persona_id: uuid.UUID, update: PersonaUpdate, session: SessionDep
) -> PersonaRead:
    return PersonaRead.of(await personas.update_persona(session, persona_id, update))


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(persona_id: uuid.UUID, session: SessionDep) -> None:
    await personas.delete_persona(session, persona_id)


@router.get("/{persona_id}/scenarios")
async def list_persona_scenarios(
    persona_id: uuid.UUID, session: SessionDep
) -> list[PersonaScenario]:
    """The live scenarios that use the persona; a persona is deleted only when none does."""
    return [
        PersonaScenario(
            id=scenario.id, name=scenario.name, agent_id=scenario.agent_id, agent_name=agent_name
        )
        for scenario, agent_name in await personas.persona_scenarios(session, persona_id)
    ]


@router.get("/{persona_id}/versions")
async def list_versions(
    persona_id: uuid.UUID, session: SessionDep, page: PageDep
) -> Page[PersonaVersionRead]:
    rows, total = await personas.list_versions(
        session, persona_id, offset=page.offset, limit=page.page_size
    )
    return Page.of([PersonaVersionRead.model_validate(row) for row in rows], total, page)


@router.get("/{persona_id}/versions/{version}")
async def get_version(
    persona_id: uuid.UUID, version: int, session: SessionDep
) -> PersonaVersionRead:
    return PersonaVersionRead.model_validate(
        await personas.get_version(session, persona_id, version)
    )
