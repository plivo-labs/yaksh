import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from truman.api.auth import LabelerDep
from truman.api.deps import SessionDep, SettingsDep
from truman.api.routes.conversations import detail
from truman.api.schemas.conversations import ItemRead
from truman.api.schemas.review import (
    LabelCreate,
    LabelRead,
    ReviewConversation,
    ReviewItem,
    ReviewVerdicts,
)
from truman.db.models import Labeler
from truman.domain.conversations import WireEventKind
from truman.domain.evaluations import Lane, QueuedReview
from truman.evaluation import labels
from truman.simulation import conversations

router = APIRouter(prefix="/review", tags=["review"])


async def reviewed(
    session: AsyncSession, conversation_id: uuid.UUID, labeler: Labeler, budget: int
) -> ReviewConversation:
    found = await labels.review(session, conversation_id, labeler.id, budget)
    base = await detail(session, await conversations.get_conversation(session, conversation_id))
    evaluation = found.evaluation
    return ReviewConversation(
        conversation=base.model_copy(
            update={
                "recording_url": f"/api/v1/review/conversations/{conversation_id}/recording"
                if base.recording_url
                else None,
                "caller_reason": None,
                "wire_events": [
                    event.model_copy(update={"detail": None})
                    if event.kind is WireEventKind.END_CALL
                    else event
                    for event in base.wire_events
                ],
            }
        ),
        lane=Lane.AUDIT if found.audit else Lane.AD_HOC,
        items=[
            ReviewItem(
                id=item.id,
                item_key=item.item_key,
                subject=item.subject,
                role=item.role,
                blind=found.blind(item),
                machine=None if found.hidden(item) else ItemRead.model_validate(item),
                label=LabelRead.model_validate(found.labels[item.id])
                if item.id in found.labels
                else None,
            )
            for item in found.items
        ],
        verdicts=None
        if found.verdicts_hidden
        else ReviewVerdicts(
            scenario_verdict=evaluation.scenario_verdict,
            conversation_verdict=evaluation.conversation_verdict,
            effective_scenario_verdict=evaluation.effective_scenario_verdict,
            effective_conversation_verdict=evaluation.effective_conversation_verdict,
        ),
    )


@router.get("/queue")
async def get_queue(
    labeler: LabelerDep, session: SessionDep, settings: SettingsDep
) -> list[QueuedReview]:
    """The audit calls this labeler still has items to label in."""
    return await labels.queue(session, labeler.id, settings.audit_weekly_budget)


@router.get("/conversations/{conversation_id}")
async def get_review(
    conversation_id: uuid.UUID, labeler: LabelerDep, session: SessionDep, settings: SettingsDep
) -> ReviewConversation:
    """A judged call to label. Any judged call takes labels; only the calls the queue offers
    hide the machine results, and only their labels measure the judges."""
    return await reviewed(session, conversation_id, labeler, settings.audit_weekly_budget)


@router.get("/conversations/{conversation_id}/recording")
async def get_recording(
    conversation_id: uuid.UUID, labeler: LabelerDep, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    await labels.review(session, conversation_id, labeler.id, settings.audit_weekly_budget)
    conversation = await conversations.get_conversation(session, conversation_id)
    if conversation.recording_path is None or not Path(conversation.recording_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no recording yet")
    return FileResponse(conversation.recording_path, media_type="audio/wav")


@router.post("/items/{item_id}/labels", status_code=status.HTTP_201_CREATED)
async def label_item(
    item_id: uuid.UUID,
    command: LabelCreate,
    labeler: LabelerDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ReviewConversation:
    """Label one item; the call comes back with what the label reveals."""
    budget = settings.audit_weekly_budget
    conversation_id = await labels.add_label(
        session, item_id, labeler.id, command.answer, command.reason, command.note, budget
    )
    return await reviewed(session, conversation_id, labeler, budget)
