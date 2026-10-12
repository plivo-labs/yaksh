import uuid
from collections.abc import AsyncIterable, Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.api.auth import require_token
from yaksh.api.deps import FileStoreDep, SessionDep, SettingsDep
from yaksh.api.errors import CLIENT_ERRORS, UNAVAILABLE, json_errors
from yaksh.api.files import StoredFileResponse
from yaksh.api.pagination import Page, PageDep
from yaksh.api.schemas.conversations import (
    ConversationEvaluation,
    ConversationRead,
    ConversationSummary,
    ItemRead,
    LatencySummary,
    SoundRead,
    TurnRead,
)
from yaksh.db.models import Conversation
from yaksh.domain.conversations import (
    ACTIVE_STATUSES,
    LIVE_STATUSES,
    ConversationStatus,
    OutcomeGroup,
    Role,
    Transcript,
)
from yaksh.domain.latency import Latency, place
from yaksh.evaluation import results
from yaksh.simulation import conversations
from yaksh.simulation.listen import live_audio

SORT_PATTERN = f"^-?({'|'.join(conversations.SORT_KEYS)})$"

router = APIRouter(
    prefix="/conversations", tags=["conversations"], dependencies=[Depends(require_token)]
)

STREAM_INTERVAL_S = 0.5


def recording_url(conversation: Conversation) -> str | None:
    if conversation.recording_key is None:
        return None
    return f"/api/v1/conversations/{conversation.id}/recording"


async def summaries(
    session: AsyncSession,
    rows: list[Conversation],
    found: Mapping[uuid.UUID, results.Evaluated] | None = None,
) -> list[ConversationSummary]:
    """`found` holds evaluations already read; the rest are read here."""
    agents = await conversations.pinned_agents(session, (row.agent_version_id for row in rows))
    personas = await conversations.pinned_personas(
        session, (row.persona_version_id for row in rows)
    )
    scenarios = await conversations.pinned_scenarios(
        session, (row.scenario_version_id for row in rows)
    )
    if found is None:
        found = await results.evaluated(session, (row.id for row in rows))
    items = []
    for row in rows:
        data = {
            name: getattr(row, name)
            for name in ConversationSummary.model_fields
            if hasattr(row, name)
        }
        data["agent_version"], data["agent_name"] = agents[row.agent_version_id]
        data["persona_version"], data["persona_name"] = personas[row.persona_version_id]
        (
            data["scenario_version"],
            data["scenario_name"],
            data["scenario_data_sets"],
        ) = scenarios[row.scenario_version_id]
        data["recording_url"] = recording_url(row)
        evaluation = found.get(row.id)
        latency = evaluation.latency if evaluation else None
        data["latency"] = LatencySummary.of(latency) if latency and latency.replies else None
        data["evaluation"] = evaluation.state if evaluation else None
        items.append(ConversationSummary.model_validate(data))
    return items


async def summary(
    session: AsyncSession,
    conversation: Conversation,
    found: Mapping[uuid.UUID, results.Evaluated] | None = None,
) -> ConversationSummary:
    return (await summaries(session, [conversation], found))[0]


def turns_with_replies(transcript: Transcript, latency: Latency | None) -> list[TurnRead]:
    """The turns, each agent turn with the reply it starts with."""
    replies = latency.replies if latency else []
    agent = [index for index, turn in enumerate(transcript.turns) if turn.role is Role.AGENT]
    starts = [transcript.turns[index].started_at_ms for index in agent]
    placed = dict(zip(agent, place(starts, replies), strict=True))
    turns = []
    for index, turn in enumerate(transcript.turns):
        reply = placed.get(index)
        turns.append(
            TurnRead(
                **turn.model_dump(),
                response_ms=reply.response_ms if reply else None,
                talked_over=reply is not None and reply.response_ms is None,
            )
        )
    return turns


async def detail(session: AsyncSession, conversation: Conversation) -> ConversationRead:
    transcript = conversations.transcript_of(conversation)
    found = await results.evaluated(session, [conversation.id])
    latency = found[conversation.id].latency if conversation.id in found else None
    base = await summary(session, conversation, found)
    return ConversationRead(
        **base.model_dump(),
        instructions=conversation.instructions,
        sounds=SoundRead.all_of(conversation.sound_plan),
        scenario=await conversations.played_scenario(session, conversation),
        transcript=turns_with_replies(transcript, latency),
        replies=latency.replies if latency else [],
        wire_events=transcript.wire_events,
        validity=transcript.validity,
        retried_as=await conversations.retried_as(session, conversation),
    )


@router.get("")
async def list_conversations(
    session: SessionDep,
    page: PageDep,
    agent_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    status: ConversationStatus | None = None,
    group: Annotated[
        list[OutcomeGroup] | None,
        Query(description="conversations in any of these groups; repeat it for several"),
    ] = None,
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
        groups=group or (),
        latest_attempts=latest_attempts,
        search=q,
        sort=sort,
    )
    return Page.of(await summaries(session, rows), total, page)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationRead:
    return await detail(session, await conversations.get_conversation(session, conversation_id))


@router.get("/{conversation_id}/evaluation")
async def get_evaluation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationEvaluation:
    await conversations.get_conversation(session, conversation_id)
    evaluation, metrics, items = await results.evaluation(session, conversation_id)
    return ConversationEvaluation(
        evaluation=evaluation.state if evaluation else None,
        failure=evaluation.failure if evaluation else None,
        metrics=metrics,
        scenario_verdict=evaluation.scenario_verdict if evaluation else None,
        conversation_verdict=evaluation.conversation_verdict if evaluation else None,
        effective_scenario_verdict=evaluation.effective_scenario_verdict if evaluation else None,
        effective_conversation_verdict=(
            evaluation.effective_conversation_verdict if evaluation else None
        ),
        items=[ItemRead.model_validate(item) for item in items],
    )


@router.get("/{conversation_id}/recording", response_class=StreamingResponse, responses=UNAVAILABLE)
async def get_recording(
    conversation_id: uuid.UUID, session: SessionDep, store: FileStoreDep
) -> StreamingResponse:
    opened = await conversations.open_recording(session, store, conversation_id)
    return StoredFileResponse(opened, "audio/wav")


@router.post(
    "/{conversation_id}/end",
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": ConversationRead,
            "description": "The call of the conversation is still stopping.",
        }
    },
)
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
    responses=json_errors(CLIENT_ERRORS),
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


async def conversation_live(conversation_id: uuid.UUID, request: Request) -> None:
    async with request.app.state.sessionmaker() as session:
        conversation = await conversations.get_conversation(session, conversation_id)
    if conversation.status not in LIVE_STATUSES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the conversation is not live")


class AudioStream(StreamingResponse):
    media_type = "application/octet-stream"


@router.get(
    "/{conversation_id}/listen",
    response_class=AudioStream,
    responses=json_errors(CLIENT_ERRORS),
    dependencies=[Depends(conversation_live)],
)
async def listen(
    conversation_id: uuid.UUID, request: Request, settings: SettingsDep
) -> AudioStream:
    """Both sides of a live call's audio as the worker sends it, until the call ends. Each
    message has its length as a little-endian u32 in front, then the side (0 the agent, 1 the
    caller) as a byte, the time on the call's pipeline clock in ms as a little-endian double,
    and 8 kHz PCM16 mono audio."""
    audio = live_audio(request.app.state.sessionmaker, str(settings.database_url), conversation_id)
    return AudioStream(audio, headers={"Cache-Control": "no-store"})
