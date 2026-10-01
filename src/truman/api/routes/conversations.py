import uuid
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from truman.api.auth import require_token
from truman.api.deps import SessionDep, SettingsDep
from truman.api.pagination import Page, PageDep
from truman.api.schemas.conversations import ConversationRead, ConversationSummary
from truman.db.models import Conversation
from truman.domain.conversations import (
    ACTIVE_STATUSES,
    ConversationCreate,
    ConversationStatus,
    OutcomeGroup,
)
from truman.simulation import conversations

SORT_PATTERN = f"^-?({'|'.join(conversations.SORT_KEYS)})$"

router = APIRouter(
    prefix="/conversations", tags=["conversations"], dependencies=[Depends(require_token)]
)

STREAM_INTERVAL_S = 0.5


def recording_url(conversation: Conversation) -> str | None:
    if conversation.recording_path is None:
        return None
    return f"/api/v1/conversations/{conversation.id}/recording"


async def summaries(session: AsyncSession, rows: list[Conversation]) -> list[ConversationSummary]:
    agents = await conversations.pinned_agents(session, (row.agent_version_id for row in rows))
    personas = await conversations.pinned_personas(
        session, (row.persona_version_id for row in rows)
    )
    scenarios = await conversations.pinned_scenarios(
        session, (row.scenario_version_id for row in rows)
    )
    items = []
    for row in rows:
        data = {
            name: getattr(row, name)
            for name in ConversationSummary.model_fields
            if hasattr(row, name)
        }
        data["agent_version"], data["agent_name"] = agents[row.agent_version_id]
        data["persona_version"], data["persona_name"] = personas[row.persona_version_id]
        data["scenario_version"], data["scenario_name"] = scenarios[row.scenario_version_id]
        data["recording_url"] = recording_url(row)
        items.append(ConversationSummary.model_validate(data))
    return items


async def summary(session: AsyncSession, conversation: Conversation) -> ConversationSummary:
    return (await summaries(session, [conversation]))[0]


async def detail(session: AsyncSession, conversation: Conversation) -> ConversationRead:
    transcript = conversations.transcript_of(conversation)
    base = await summary(session, conversation)
    return ConversationRead(
        **base.model_dump(),
        instructions=conversation.instructions,
        scenario=await conversations.pinned_scenario_config(session, conversation),
        transcript=transcript.turns,
        wire_events=transcript.wire_events,
        validity=transcript.validity,
        retried_as=await conversations.retried_as(session, conversation),
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_conversation(
    command: ConversationCreate, session: SessionDep, settings: SettingsDep
) -> ConversationSummary:
    conversation = await conversations.create_conversation(session, settings, command)
    return await summary(session, conversation)


@router.get("")
async def list_conversations(
    session: SessionDep,
    page: PageDep,
    agent_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    status: ConversationStatus | None = None,
    group: OutcomeGroup | None = None,
    latest_attempts: Annotated[
        bool, Query(description="true leaves out the attempts that a retry replaced")
    ] = False,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str, Query(pattern=SORT_PATTERN)] = "-created_at",
) -> Page[ConversationSummary]:
    rows, total = await conversations.list_conversations(
        session,
        offset=page.offset,
        limit=page.page_size,
        agent_id=agent_id,
        run_id=run_id,
        status=status,
        group=group,
        latest_attempts=latest_attempts,
        search=q,
        sort=sort,
    )
    return Page.of(await summaries(session, rows), total, page)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationRead:
    return await detail(session, await conversations.get_conversation(session, conversation_id))


@router.get("/{conversation_id}/recording")
async def get_recording(conversation_id: uuid.UUID, session: SessionDep) -> FileResponse:
    conversation = await conversations.get_conversation(session, conversation_id)
    if conversation.recording_path is None or not Path(conversation.recording_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no recording yet")
    return FileResponse(conversation.recording_path, media_type="audio/wav")


@router.post("/{conversation_id}/end")
async def end_conversation(
    conversation_id: uuid.UUID, session: SessionDep, response: Response
) -> ConversationRead:
    conversation = await conversations.end_conversation(session, conversation_id)
    if conversation.status in ACTIVE_STATUSES:
        response.status_code = status.HTTP_202_ACCEPTED
    return await detail(session, conversation)


async def conversation_exists(conversation_id: uuid.UUID, request: Request) -> None:
    async with request.app.state.sessionmaker() as session:
        await conversations.get_conversation(session, conversation_id)


@router.get(
    "/{conversation_id}/events",
    response_class=EventSourceResponse,
    dependencies=[Depends(conversation_exists)],
)
async def stream_events(
    conversation_id: uuid.UUID, request: Request
) -> AsyncIterable[ServerSentEvent]:
    events = conversations.stream_events(
        request.app.state.sessionmaker, conversation_id, interval_s=STREAM_INTERVAL_S
    )
    async for event, data in events:
        yield ServerSentEvent(data=data, event=event)
