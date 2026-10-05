import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from truman.api.schemas.conversations import ConversationRead, ItemRead
from truman.domain.evaluations import (
    NEEDS_REASON,
    ItemRole,
    LabelAnswer,
    LabelReason,
    Lane,
    Verdict,
)

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class LabelerCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class LabelerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    revoked_at: datetime | None


class LabelerCreated(BaseModel):
    id: uuid.UUID
    name: str
    token: str
    """Shown once: only its hash is stored."""


class LabelCreate(BaseModel):
    answer: LabelAnswer
    reason: LabelReason | None = None
    """Needed for a fail, can't tell or blocked."""
    note: Note | None = None
    seen: bool = False
    """The labeler saw the machine's results first, as from the conversation page: the label
    is then ad hoc, whatever the call."""

    @model_validator(mode="after")
    def reason_given(self) -> Self:
        if self.answer in NEEDS_REASON and self.reason is None:
            raise ValueError("a fail, can't tell or blocked label needs a reason")
        if self.reason is LabelReason.OTHER and self.note is None:
            raise ValueError("the reason other needs a note")
        return self


class LabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: LabelAnswer
    reason: LabelReason | None
    note: str | None
    lane: Lane
    blind: bool
    created_at: datetime


class ReviewItem(BaseModel):
    id: uuid.UUID
    item_key: str
    subject: str
    role: ItemRole
    blind: bool
    """The item is in the audit lane, and this labeler has not labeled it: its label will be
    blind."""
    machine: ItemRead | None
    """None while the item is blind, and, in an audit call, for every item until the labeler
    has labeled each auditable one."""
    label: LabelRead | None
    """This labeler's latest label."""


class ReviewVerdicts(BaseModel):
    scenario_verdict: Verdict | None
    conversation_verdict: Verdict | None
    effective_scenario_verdict: Verdict | None
    effective_conversation_verdict: Verdict | None


class ReviewConversation(BaseModel):
    conversation: ConversationRead
    """Without the caller's reason for ending the call, which judges do not see either."""
    lane: Lane
    """Audit when the review queue offers the call; its auditable items then take audit
    labels."""
    items: list[ReviewItem]
    verdicts: ReviewVerdicts | None
    """None until this labeler has labeled every blind item."""
