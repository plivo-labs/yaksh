import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from yaksha.api.auth import LabelerDep
from yaksha.api.deps import AppSettingsDep, FileStoreDep, SessionDep
from yaksha.api.errors import UNAVAILABLE
from yaksha.api.routes.conversations import detail
from yaksha.api.schemas.conversations import ItemRead
from yaksha.api.schemas.review import (
    LabelCreate,
    LabelRead,
    ReviewConversation,
    ReviewItem,
    ReviewVerdicts,
)
from yaksha.db.models import Labeler
from yaksha.domain.conversations import WireEventKind
from yaksha.domain.evaluations import Lane, QueuedReview
from yaksha.evaluation import labels
from yaksha.simulation import conversations

router = APIRouter(prefix="/review", tags=["review"])


async def reviewed(
    session: AsyncSession, conversation_id: uuid.UUID, labeler: Labeler, budget: int, *, seen: bool
) -> ReviewConversation:
    found = await labels.review(session, conversation_id, labeler.id, budget, seen=seen)
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
    labeler: LabelerDep, session: SessionDep, settings: AppSettingsDep
) -> list[QueuedReview]:
    """The audit calls this labeler still has items to label in."""
    return await labels.queue(session, labeler.id, settings.audit.weekly_budget)


@router.get("/conversations/{conversation_id}")
async def get_review(
    conversation_id: uuid.UUID,
    labeler: LabelerDep,
    session: SessionDep,
    settings: AppSettingsDep,
    seen: bool = False,
) -> ReviewConversation:
    """A judged call to label. Any judged call takes labels; only the calls the queue offers
    hide the machine results, and only their labels measure the judges. `seen`: the labeler
    came from the machine's results, so the call is ad hoc."""
    return await reviewed(
        session, conversation_id, labeler, settings.audit.weekly_budget, seen=seen
    )


@router.get(
    "/conversations/{conversation_id}/recording", response_class=Response, responses=UNAVAILABLE
)
async def get_recording(
    conversation_id: uuid.UUID,
    labeler: LabelerDep,
    session: SessionDep,
    settings: AppSettingsDep,
    store: FileStoreDep,
) -> Response:
    # Only checks that the call is judged: what a labeler may see does not depend on the audio.
    await labels.review(
        session, conversation_id, labeler.id, settings.audit.weekly_budget, seen=True
    )
    recording = await conversations.get_recording(session, store, conversation_id)
    return Response(recording, media_type="audio/wav")


@router.post("/items/{item_id}/labels", status_code=status.HTTP_201_CREATED)
async def label_item(
    item_id: uuid.UUID,
    command: LabelCreate,
    labeler: LabelerDep,
    session: SessionDep,
    settings: AppSettingsDep,
) -> ReviewConversation:
    """Label one item; the call comes back with what the label reveals."""
    budget = settings.audit.weekly_budget
    conversation_id = await labels.add_label(
        session,
        item_id,
        labeler.id,
        command.answer,
        command.reason,
        command.note,
        budget,
        seen=command.seen,
    )
    return await reviewed(session, conversation_id, labeler, budget, seen=command.seen)
