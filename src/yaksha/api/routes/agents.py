import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from yaksha.api.auth import require_token
from yaksha.api.deps import BriefModelDep, GenerationModelDep, SessionDep
from yaksha.api.errors import UNAVAILABLE
from yaksha.api.pagination import Page, PageDep
from yaksha.api.schemas.agents import AgentRead, AgentSummary, AgentVersionRead
from yaksha.db.models import Agent
from yaksha.domain.agent_import import (
    AgentDraft,
    AgentFile,
    CurlCommand,
    ElevenLabsAgentChoice,
    ElevenLabsAgentPage,
    ElevenLabsAgentSearch,
    PlivoCxFlowChoice,
    PlivoCxFlowPage,
    PlivoCxFlowSearch,
    ProviderDraft,
    RetellAgentChoice,
    RetellAgentPage,
    RetellAgentSearch,
    StartRequestDraft,
    VapiAssistantChoice,
    VapiAssistantPage,
    VapiAssistantSearch,
)
from yaksha.domain.agents import (
    AgentCreate,
    AgentSource,
    AgentUpdate,
    BriefDraft,
    BriefSource,
    Direction,
)
from yaksha.domain.evaluations import RuleResults
from yaksha.evaluation import rule_results
from yaksha.simulation import (
    agents,
    elevenlabs_import,
    generation,
    plivo_cx_import,
    retell_import,
    vapi_import,
)
from yaksha.simulation.agent_import import import_agent
from yaksha.simulation.briefs import draft_brief
from yaksha.simulation.curl_import import start_request_from_curl

SORT_PATTERN = f"^-?({'|'.join(agents.SORT_KEYS)})$"


async def agent_read(session: SessionDep, agent: Agent) -> AgentRead:
    return AgentRead.of(agent, await agents.knowledge_base_documents(session, agent))


router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(require_token)])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    command: AgentCreate, session: SessionDep, request: Request, model: GenerationModelDep
) -> AgentRead:
    """Saves the agent and, unless write_scenarios is false, starts writing its first scenarios.
    They arrive after the response: GET /agents/{id}/scenario-generations shows the progress."""
    agent = await agents.create_agent(session, command)
    if command.write_scenarios:
        prepared = await generation.first_generation(session, model, agent.id)
        if prepared is not None:
            sessionmaker = request.app.state.sessionmaker
            generation_id = await generation.open_generation(sessionmaker, prepared)
            request.app.state.generations.start(prepared, generation_id)
    return await agent_read(session, agent)


@router.post("/import")
async def import_agent_file(file: AgentFile) -> AgentDraft:
    """Read an agent file from another platform into a draft. Nothing is saved. A file in a format
    that Yaksha does not read fails with the code `not_recognized`; it can still be the config."""
    return import_agent(file.content)


@router.post("/import/plivo-cx/flows", responses=UNAVAILABLE)
async def list_plivo_cx_flows(search: PlivoCxFlowSearch, request: Request) -> PlivoCxFlowPage:
    """One page of a Plivo CX account's agent flows. The credentials are used for this call
    only."""
    api = request.app.state.providers.plivo_cx(search.auth_id, search.auth_token)
    return await plivo_cx_import.list_flows(api, search)


@router.post("/import/plivo-cx/flow", responses=UNAVAILABLE)
async def import_plivo_cx_flow(choice: PlivoCxFlowChoice, request: Request) -> ProviderDraft:
    """Read one Plivo CX agent flow into a draft agent. Nothing is saved. A flow that a request
    starts gets a start request that carries the credentials, as Plivo CX's "Copy cURL" does."""
    api = request.app.state.providers.plivo_cx(choice.auth_id, choice.auth_token)
    return await plivo_cx_import.import_flow(api, choice.flow_id)


@router.post("/import/elevenlabs/agents", responses=UNAVAILABLE)
async def list_elevenlabs_agents(
    search: ElevenLabsAgentSearch, request: Request
) -> ElevenLabsAgentPage:
    """One page of an ElevenLabs workspace's agents. The API key is used for this call only."""
    api = request.app.state.providers.elevenlabs_agents(search.api_key, search.region)
    return await elevenlabs_import.list_agents(api, search)


@router.post("/import/elevenlabs/agent", responses=UNAVAILABLE)
async def import_elevenlabs_agent(choice: ElevenLabsAgentChoice, request: Request) -> ProviderDraft:
    """Read one ElevenLabs agent into a draft agent. Nothing is saved. An agent without a number
    gets a start request for ElevenLabs' outbound call, which carries the API key."""
    api = request.app.state.providers.elevenlabs_agents(choice.api_key, choice.region)
    return await elevenlabs_import.import_agent(api, choice.agent_id)


@router.post("/import/vapi/assistants", responses=UNAVAILABLE)
async def list_vapi_assistants(search: VapiAssistantSearch, request: Request) -> VapiAssistantPage:
    """One page of a Vapi organization's assistants, newest first. The API key is used for this
    call only."""
    api = request.app.state.providers.vapi(search.api_key, search.region)
    return await vapi_import.list_assistants(api, search)


@router.post("/import/vapi/assistant", responses=UNAVAILABLE)
async def import_vapi_assistant(choice: VapiAssistantChoice, request: Request) -> ProviderDraft:
    """Read one Vapi assistant into a draft agent. Nothing is saved. An assistant without a
    number gets a start request for Vapi's outbound call, which carries the API key."""
    api = request.app.state.providers.vapi(choice.api_key, choice.region)
    return await vapi_import.import_assistant(api, str(choice.assistant_id))


@router.post("/import/retell/agents", responses=UNAVAILABLE)
async def list_retell_agents(search: RetellAgentSearch, request: Request) -> RetellAgentPage:
    """One page of a Retell workspace's voice agents. The API key is used for this call only."""
    api = request.app.state.providers.retell(search.api_key)
    return await retell_import.list_agents(api, search)


@router.post("/import/retell/agent", responses=UNAVAILABLE)
async def import_retell_agent(choice: RetellAgentChoice, request: Request) -> ProviderDraft:
    """Read the published version of one Retell agent into a draft agent. Nothing is saved. An
    agent without a number gets a start request for Retell's outbound call, which carries the API
    key."""
    api = request.app.state.providers.retell(choice.api_key)
    return await retell_import.import_agent(api, choice.agent_id)


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
    source: AgentSource | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str, Query(pattern=SORT_PATTERN)] = "-created_at",
) -> Page[AgentSummary]:
    rows, total = await agents.list_agents(
        session,
        offset=page.offset,
        limit=page.page_size,
        external_id=external_id,
        direction=direction,
        source=source,
        search=q,
        sort=sort,
    )
    return Page.of([AgentSummary.model_validate(row) for row in rows], total, page)


@router.get("/sources")
async def list_agent_sources(session: SessionDep) -> list[AgentSource]:
    """Where the live agents came from, each source once."""
    return await agents.agent_sources(session)


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
