import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from yaksha.api.auth import require_token
from yaksha.api.deps import BriefModelDep, SessionDep
from yaksha.api.errors import UNAVAILABLE
from yaksha.api.pagination import Page, PageDep
from yaksha.api.schemas.agents import AgentRead, AgentSummary, AgentVersionRead
from yaksha.db.models import Agent
from yaksha.domain.agent_import import AgentDraft, AgentFile, CurlCommand, StartRequestDraft
from yaksha.domain.agents import AgentCreate, AgentUpdate, BriefDraft, BriefSource, Direction
from yaksha.domain.evaluations import RuleResults
from yaksha.evaluation import rule_results
from yaksha.simulation import agents
from yaksha.simulation.agent_import import import_agent
from yaksha.simulation.briefs import draft_brief
from yaksha.simulation.curl_import import start_request_from_curl

SORT_PATTERN = f"^-?({'|'.join(agents.SORT_KEYS)})$"


async def agent_read(session: SessionDep, agent: Agent) -> AgentRead:
    return AgentRead.of(agent, await agents.knowledge_base_documents(session, agent))


router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(require_token)])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(command: AgentCreate, session: SessionDep) -> AgentRead:
    return await agent_read(session, await agents.create_agent(session, command))


@router.post("/import")
async def import_agent_file(file: AgentFile) -> AgentDraft:
    """Read an agent file from another platform into a draft. Nothing is saved. A file in a format
    that Yaksha does not read fails with the code `not_recognized`; it can still be the config."""
    return import_agent(file.content)


@router.post("/start-request-from-curl")
async def read_curl_command(curl: CurlCommand) -> StartRequestDraft:
    """Read a cURL command into a start request, for an agent that calls Yaksha. Nothing is
    saved. A body field or query parameter that looks like the number to call gets
    `{{yaksha.number}}`."""
    return start_request_from_curl(curl.command)


@router.post("/draft-brief", responses=UNAVAILABLE)
async def draft_agent_brief(source: BriefSource, model: BriefModelDep) -> BriefDraft:
    """Draft a brief from an agent's config, for the person to check and change. Nothing is
    saved."""
    return BriefDraft(brief=await draft_brief(model, source.config))


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
