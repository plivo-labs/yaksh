import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from yaksha.api.auth import require_token
from yaksha.api.deps import SessionDep
from yaksha.api.pagination import Page, PageDep
from yaksha.api.schemas.agents import AgentRead, AgentSummary, AgentVersionRead
from yaksha.db.models import Agent
from yaksha.domain.agents import AgentCreate, AgentUpdate, Direction
from yaksha.domain.evaluations import RuleResults
from yaksha.evaluation import rule_results
from yaksha.simulation import agents

SORT_PATTERN = f"^-?({'|'.join(agents.SORT_KEYS)})$"


async def agent_read(session: SessionDep, agent: Agent) -> AgentRead:
    return AgentRead.of(agent, await agents.knowledge_base_documents(session, agent))


router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(require_token)])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(command: AgentCreate, session: SessionDep) -> AgentRead:
    return await agent_read(session, await agents.create_agent(session, command))


@router.get("")
async def list_agents(
    session: SessionDep,
    page: PageDep,
    external_id: str | None = None,
    direction: Direction | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str, Query(pattern=SORT_PATTERN)] = "-created_at",
) -> Page[AgentSummary]:
    rows, total = await agents.list_agents(
        session,
        offset=page.offset,
        limit=page.page_size,
        external_id=external_id,
        direction=direction,
        search=q,
        sort=sort,
    )
    return Page.of([AgentSummary.model_validate(row) for row in rows], total, page)


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, session: SessionDep) -> AgentRead:
    return await agent_read(session, await agents.get_agent(session, agent_id))


@router.patch("/{agent_id}")
async def update_agent(agent_id: uuid.UUID, update: AgentUpdate, session: SessionDep) -> AgentRead:
    return await agent_read(session, await agents.update_agent(session, agent_id, update))


@router.post("/{agent_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_agent(agent_id: uuid.UUID, session: SessionDep) -> AgentRead:
    return await agent_read(session, await agents.duplicate_agent(session, agent_id))


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, session: SessionDep) -> None:
    await agents.delete_agent(session, agent_id)


@router.get("/{agent_id}/rule-results")
async def get_rule_results(agent_id: uuid.UUID, session: SessionDep) -> list[RuleResults]:
    """Each current rule over the judged calls that ran it as it is written now."""
    agent = await agents.get_agent(session, agent_id)
    return await rule_results.rule_results(session, agent_id, agents.config_of(agent).rules)


@router.get("/{agent_id}/versions")
async def list_versions(
    agent_id: uuid.UUID, session: SessionDep, page: PageDep
) -> Page[AgentVersionRead]:
    rows, total = await agents.list_versions(
        session, agent_id, offset=page.offset, limit=page.page_size
    )
    return Page.of([AgentVersionRead.model_validate(row) for row in rows], total, page)


@router.get("/{agent_id}/versions/{version}")
async def get_version(agent_id: uuid.UUID, version: int, session: SessionDep) -> AgentVersionRead:
    return AgentVersionRead.model_validate(await agents.get_version(session, agent_id, version))
