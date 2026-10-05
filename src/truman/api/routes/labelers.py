import uuid

from fastapi import APIRouter, Depends, status

from truman.api.auth import require_token
from truman.api.deps import SessionDep
from truman.api.schemas.review import LabelerCreate, LabelerCreated, LabelerRead
from truman.evaluation import labels

router = APIRouter(prefix="/labelers", tags=["labelers"], dependencies=[Depends(require_token)])


@router.get("")
async def list_labelers(session: SessionDep) -> list[LabelerRead]:
    return [LabelerRead.model_validate(labeler) for labeler in await labels.labelers(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_labeler(command: LabelerCreate, session: SessionDep) -> LabelerCreated:
    """A labeler and the token it labels with, shown only in this answer."""
    labeler, token = await labels.create_labeler(session, command.name)
    return LabelerCreated(id=labeler.id, name=labeler.name, token=token)


@router.delete("/{labeler_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_labeler(labeler_id: uuid.UUID, session: SessionDep) -> None:
    """The labeler's token stops working; its labels stay."""
    await labels.revoke_labeler(session, labeler_id)


@router.post("/{labeler_id}/token")
async def renew_token(labeler_id: uuid.UUID, session: SessionDep) -> LabelerCreated:
    """A new token for the labeler, shown only in this answer; the old one stops working, and a
    revoked labeler works again."""
    labeler, token = await labels.new_token(session, labeler_id)
    return LabelerCreated(id=labeler.id, name=labeler.name, token=token)
