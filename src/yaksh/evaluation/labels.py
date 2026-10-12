"""People's labels: a labeler's answer for one judged item. A label never overwrites the machine
result; it sets the effective one.

Of the judged calls, a random sample by hash is audited; the review queue offers each week's
first audit calls by hash, up to a budget. A label is in the audit lane only when the queue
offers its call and its item is auditable: one the judge model or Jev decided without an error.
Blind labels in the audit lane measure the judges. Every other label is ad hoc: it changes the
effective results but never measures a judge, since a person chose the call."""

import hashlib
import secrets
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import Row, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import (
    Conversation,
    Evaluation,
    EvaluationItem,
    JudgeVersion,
    Label,
    Labeler,
    Scenario,
)
from yaksh.domain.errors import ConflictError, NotFoundError, ValidationError
from yaksh.domain.evaluations import (
    DecidedBy,
    EvaluationState,
    JudgeAgreement,
    LabelAnswer,
    LabelReason,
    Lane,
    Outcome,
    QueuedReview,
    Share,
    UnsureKind,
    Verdict,
    VersionAgreement,
)
from yaksh.evaluation.verdicts import CRITERION, counted, scored_as, verdict

LABELER_NAME = "uq_labelers_name"
SOURCE_ITEMS = frozenset({"instructions", "hallucination"})
"""Their judges read the agent's config and documents, which the review screen does not show."""
UNMEASURED = frozenset({Outcome.BLOCKED, Outcome.ERROR})
"""Outcomes no judge version answered: the caller check blocked the item, or the judge failed."""


def hash_fraction(conversation_id: uuid.UUID) -> float:
    """Where the conversation falls in [0, 1), the same every time: the audit sample is the
    judged calls below the sample rate, and the queue offers them in this order."""
    digest = hashlib.sha256(conversation_id.bytes).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_labeler(session: AsyncSession, name: str) -> tuple[Labeler, str]:
    """The new labeler and its token. Only the token's hash is stored, so this is the one time
    anyone sees the token."""
    token = secrets.token_urlsafe(32)
    labeler = Labeler(name=name, token_sha256=token_sha256(token))
    session.add(labeler)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if LABELER_NAME in str(exc.orig):
            raise ConflictError("name is already used by another labeler") from exc
        raise
    return labeler, token


async def labelers(session: AsyncSession) -> list[Labeler]:
    return list(await session.scalars(select(Labeler).order_by(Labeler.name)))


async def revoke_labeler(session: AsyncSession, labeler_id: uuid.UUID) -> None:
    """The labeler's token stops working; its labels stay."""
    revoked = await session.scalar(
        update(Labeler)
        .where(Labeler.id == labeler_id)
        .values(revoked_at=func.coalesce(Labeler.revoked_at, func.now()))
        .returning(Labeler.id)
    )
    if revoked is None:
        raise NotFoundError("no labeler with this id")
    await session.commit()


async def new_token(session: AsyncSession, labeler_id: uuid.UUID) -> tuple[Labeler, str]:
    """A new token for the same labeler, which also ends a revocation: a person keeps one
    labeler, so their labels never count as two people's."""
    token = secrets.token_urlsafe(32)
    labeler = await session.scalar(
        update(Labeler)
        .where(Labeler.id == labeler_id)
        .values(token_sha256=token_sha256(token), revoked_at=None)
        .returning(Labeler)
    )
    if labeler is None:
        raise NotFoundError("no labeler with this id")
    await session.commit()
    return labeler, token


async def labeler_with_token(session: AsyncSession, token: str) -> Labeler | None:
    return await session.scalar(
        select(Labeler).where(
            Labeler.token_sha256 == token_sha256(token), Labeler.revoked_at.is_(None)
        )
    )


def auditable(decided_by: DecidedBy, machine_outcome: Outcome, item_key: str) -> bool:
    """An item whose blind labels can measure the judge that decided it."""
    return (
        decided_by is not DecidedBy.CODE
        and machine_outcome is not Outcome.ERROR
        and item_key not in SOURCE_ITEMS
    )


def week_of(at: datetime) -> datetime:
    """The start of the UTC week, from Monday, that holds this time."""
    day = at.astimezone(UTC).date()
    return datetime.combine(day - timedelta(days=day.weekday()), time(), UTC)


async def offered(
    session: AsyncSession, budget: int, week: datetime | None = None
) -> list[Row[Any]]:
    """The audit calls the review queue offers, of every week or of the week that starts at
    `week`: of each week's audit evaluations, by the week the evaluation ended, the first
    `budget` by hash; the latest week first."""
    # ponytail: reads every audit evaluation; keep only recent weeks if the table grows large.
    query = (
        select(
            Evaluation.id,
            Evaluation.conversation_id,
            Evaluation.ended_at,
            Scenario.name.label("scenario_name"),
        )
        .join(Conversation, Conversation.id == Evaluation.conversation_id)
        .join(Scenario, Scenario.id == Conversation.scenario_id)
        .where(Evaluation.audit, Evaluation.state == EvaluationState.DONE)
    )
    if week is not None:
        query = query.where(
            Evaluation.ended_at >= week, Evaluation.ended_at < week + timedelta(days=7)
        )
    weeks: dict[datetime, list[Row[Any]]] = defaultdict(list)
    for row in await session.execute(query):
        weeks[week_of(row.ended_at)].append(row)
    return [
        row
        for start in sorted(weeks, reverse=True)
        for row in sorted(weeks[start], key=lambda row: hash_fraction(row.conversation_id))[:budget]
    ]


async def in_audit_lane(session: AsyncSession, evaluation: Evaluation, budget: int) -> bool:
    if not evaluation.audit or evaluation.ended_at is None:
        return False
    week = await offered(session, budget, week_of(evaluation.ended_at))
    return evaluation.id in {row.id for row in week}


@dataclass(frozen=True)
class GivenLabel:
    labeler_id: uuid.UUID
    answer: LabelAnswer
    reason: LabelReason | None


OUTCOMES = {
    LabelAnswer.PASS: Outcome.PASS,
    LabelAnswer.FAIL: Outcome.FAIL,
    LabelAnswer.NOT_APPLICABLE: Outcome.NOT_APPLICABLE,
    LabelAnswer.CANNOT_TELL: Outcome.UNSURE,
    LabelAnswer.BLOCKED: Outcome.BLOCKED,
}


def outcome_of(
    answer: LabelAnswer, reason: LabelReason | None
) -> tuple[Outcome, UnsureKind | None]:
    """A label as an item outcome. "Can't tell" with the reason hidden_action counts like the
    machine's hidden action."""
    if answer is not LabelAnswer.CANNOT_TELL:
        return OUTCOMES[answer], None
    if reason is LabelReason.HIDDEN_ACTION:
        return Outcome.UNSURE, UnsureKind.HIDDEN_ACTION
    return Outcome.UNSURE, UnsureKind.UNCLEAR


def effective(
    machine: Outcome, machine_kind: UnsureKind | None, labels: Sequence[GivenLabel]
) -> tuple[Outcome, UnsureKind | None]:
    """The item's effective outcome from its labels, oldest first: the machine's while no one
    labeled it; the labelers' answer when the latest labels of all of them agree; pending while
    they disagree."""
    latest = {label.labeler_id: label for label in labels}
    if not latest:
        return machine, machine_kind
    answers = {outcome_of(label.answer, label.reason) for label in latest.values()}
    if len(answers) > 1:
        return Outcome.PENDING, None
    [answer] = answers
    return answer


async def add_label(
    session: AsyncSession,
    item_id: uuid.UUID,
    labeler_id: uuid.UUID,
    answer: LabelAnswer,
    reason: LabelReason | None,
    note: str | None,
    budget: int,
    *,
    seen: bool,
) -> uuid.UUID:
    """Store the label and the item's and the evaluation's new effective results, in one
    transaction; return the conversation's id. The evaluation's lock orders labels of the same
    call, so each recomputation reads the effective outcomes the earlier ones wrote. `seen`: the
    labeler saw the machine's results first, as from the conversation page, so the label is ad
    hoc. A label given with the machine's answer in view says why when it differs."""
    evaluation_id = await session.scalar(
        select(EvaluationItem.evaluation_id).where(EvaluationItem.id == item_id)
    )
    if evaluation_id is None:
        raise NotFoundError("no item with this id")
    evaluation = await session.scalar(
        select(Evaluation).where(Evaluation.id == evaluation_id).with_for_update()
    )
    if evaluation is None or evaluation.scenario_verdict is None:
        raise ConflictError("only the items of a judged call take labels")
    items = (
        await session.scalars(
            select(EvaluationItem).where(EvaluationItem.evaluation_id == evaluation_id)
        )
    ).all()
    item = next(item for item in items if item.id == item_id)
    view = await viewed(session, evaluation, list(items), labeler_id, budget, seen=seen)
    differs = scored_as(*outcome_of(answer, reason)) is not scored_as(
        item.machine_outcome, item.unsure_kind
    )
    if not view.hidden(item) and differs and reason is None:
        raise ValidationError("a label that differs from the machine's answer needs a reason")
    session.add(
        Label(
            item_id=item_id,
            labeler_id=labeler_id,
            lane=Lane.AUDIT if view.auditable(item) else Lane.AD_HOC,
            blind=view.blind(item),
            answer=answer,
            reason=reason,
            note=note,
            created_at=func.statement_timestamp(),
        )
    )
    await session.flush()
    given = await session.execute(
        select(Label.labeler_id, Label.answer, Label.reason)
        .where(Label.item_id == item_id)
        .order_by(Label.created_at, Label.id)
    )
    item.effective_outcome, item.effective_unsure_kind = effective(
        item.machine_outcome, item.unsure_kind, [GivenLabel(*row) for row in given]
    )
    evaluation.effective_scenario_verdict = recomputed(items, criteria_only=True)
    evaluation.effective_conversation_verdict = recomputed(items, criteria_only=False)
    conversation_id = evaluation.conversation_id
    await session.commit()
    return conversation_id


def recomputed(items: Iterable[EvaluationItem], *, criteria_only: bool) -> Verdict:
    return verdict(
        (item.effective_outcome, item.effective_unsure_kind)
        for item in items
        if counted(item.item_key, item.role, criteria_only=criteria_only)
    )


@dataclass(frozen=True)
class Review:
    """A judged call as one labeler sees it. In a call of the audit lane, each auditable item
    hides its machine result from a labeler until that labeler labels it; the call's verdicts,
    and the items code decided, stay hidden until every auditable item is labeled."""

    evaluation: Evaluation
    audit: bool
    """The queue offers this call: its auditable items take audit labels."""
    items: list[EvaluationItem]
    labels: dict[uuid.UUID, Label]
    """This labeler's latest label of each item it labeled."""

    def auditable(self, item: EvaluationItem) -> bool:
        return self.audit and auditable(item.decided_by, item.machine_outcome, item.item_key)

    def blind(self, item: EvaluationItem) -> bool:
        return self.auditable(item) and item.id not in self.labels

    @property
    def verdicts_hidden(self) -> bool:
        return any(self.blind(item) for item in self.items)

    def hidden(self, item: EvaluationItem) -> bool:
        return self.blind(item) or (
            self.audit and not self.auditable(item) and self.verdicts_hidden
        )


async def review(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    labeler_id: uuid.UUID,
    budget: int,
    *,
    seen: bool,
) -> Review:
    """`seen`: the labeler saw the machine's results first, so nothing is hidden and the call
    takes only ad hoc labels."""
    evaluation = await session.scalar(
        select(Evaluation).where(
            Evaluation.conversation_id == conversation_id,
            Evaluation.scenario_verdict.is_not(None),
        )
    )
    if evaluation is None:
        raise NotFoundError("no judged call with this id")
    items = (
        await session.scalars(
            select(EvaluationItem)
            .where(EvaluationItem.evaluation_id == evaluation.id)
            .order_by(EvaluationItem.created_at, EvaluationItem.id)
        )
    ).all()
    return await viewed(session, evaluation, list(items), labeler_id, budget, seen=seen)


async def viewed(
    session: AsyncSession,
    evaluation: Evaluation,
    items: list[EvaluationItem],
    labeler_id: uuid.UUID,
    budget: int,
    *,
    seen: bool,
) -> Review:
    """The call as the labeler sees it now, from its labels so far."""
    labels = await session.scalars(
        select(Label)
        .where(Label.item_id.in_([item.id for item in items]), Label.labeler_id == labeler_id)
        .order_by(Label.created_at, Label.id)
    )
    return Review(
        evaluation=evaluation,
        audit=not seen and await in_audit_lane(session, evaluation, budget),
        items=items,
        labels={label.item_id: label for label in labels},
    )


async def audit_items(
    session: AsyncSession, evaluation_ids: Sequence[uuid.UUID], labeler_id: uuid.UUID | None
) -> dict[uuid.UUID, tuple[int, int]]:
    """For each evaluation, its auditable items and how many of them have a label in the audit
    lane: this labeler's, or anyone's."""
    by = [Label.labeler_id == labeler_id] if labeler_id is not None else []
    labeled = exists().where(Label.item_id == EvaluationItem.id, Label.lane == Lane.AUDIT, *by)
    rows = await session.execute(
        select(
            EvaluationItem.evaluation_id,
            EvaluationItem.decided_by,
            EvaluationItem.machine_outcome,
            EvaluationItem.item_key,
            labeled.label("labeled"),
        ).where(EvaluationItem.evaluation_id.in_(evaluation_ids))
    )
    counts: dict[uuid.UUID, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for row in rows:
        if auditable(row.decided_by, row.machine_outcome, row.item_key):
            items, done = counts[row.evaluation_id]
            counts[row.evaluation_id] = (items + 1, done + row.labeled)
    return counts


async def queue(session: AsyncSession, labeler_id: uuid.UUID, budget: int) -> list[QueuedReview]:
    """The offered calls with auditable items this labeler has not labeled."""
    calls = await offered(session, budget)
    counts = await audit_items(session, [row.id for row in calls], labeler_id)
    return [
        QueuedReview(
            conversation_id=row.conversation_id,
            scenario_name=row.scenario_name,
            ended_at=row.ended_at,
            items=counts[row.id][0],
            labeled=counts[row.id][1],
        )
        for row in calls
        if counts[row.id][1] < counts[row.id][0]
    ]


async def agreement(session: AsyncSession, budget: int) -> JudgeAgreement:
    """How often blind audit labels agree with the machine, counting each item once, by its
    first blind label. Per judge version, over the items it decided, without the ones the caller
    check blocked or the judge failed; per call, the scenario verdict of the labels against the
    machine's, over calls with a blind label on every criterion. Outcomes compare as a verdict
    counts them. Labelers' agreement with each other and how much of the offered set is labeled
    come with it."""
    rows = (
        await session.execute(
            select(
                Label.item_id,
                Label.labeler_id,
                Label.answer,
                Label.reason,
                EvaluationItem.evaluation_id,
                EvaluationItem.item_key,
                EvaluationItem.decided_by,
                EvaluationItem.machine_outcome,
                EvaluationItem.unsure_kind,
                EvaluationItem.judge_version_id,
                EvaluationItem.jev_version_id,
            )
            .join(EvaluationItem, EvaluationItem.id == Label.item_id)
            .where(Label.lane == Lane.AUDIT, Label.blind)
            .order_by(Label.created_at, Label.id)
        )
    ).all()
    by_item: dict[uuid.UUID, list[Row[Any]]] = defaultdict(list)
    for row in rows:
        by_item[row.item_id].append(row)
    by_version: dict[uuid.UUID, list[bool]] = defaultdict(list)
    by_call: dict[uuid.UUID, list[tuple[Outcome, UnsureKind | None]]] = defaultdict(list)
    pairs = []
    for labeled in by_item.values():
        first = labeled[0]
        given = outcome_of(first.answer, first.reason)
        version = (
            first.jev_version_id if first.decided_by is DecidedBy.JEV else first.judge_version_id
        )
        if version is not None and first.machine_outcome not in UNMEASURED:
            by_version[version].append(
                scored_as(*given) is scored_as(first.machine_outcome, first.unsure_kind)
            )
        if first.item_key.startswith(CRITERION):
            by_call[first.evaluation_id].append(given)
        if len(labeled) > 1:
            second = outcome_of(labeled[1].answer, labeled[1].reason)
            pairs.append(scored_as(*given) is scored_as(*second))
    calls = await offered(session, budget)
    counts = await audit_items(session, [row.id for row in calls], None)
    labeled_calls = sum(
        counts[row.id][0] > 0 and counts[row.id][1] == counts[row.id][0] for row in calls
    )
    return JudgeAgreement(
        versions=await version_agreement(session, by_version),
        conversations=await call_agreement(session, by_call),
        labelers=Share.of(sum(pairs), len(pairs)),
        offered_calls=Share.of(labeled_calls, len(calls)),
    )


async def version_agreement(
    session: AsyncSession, by_version: dict[uuid.UUID, list[bool]]
) -> list[VersionAgreement]:
    if not by_version:
        return []
    versions = await session.scalars(
        select(JudgeVersion)
        .where(JudgeVersion.id.in_(by_version))
        .order_by(JudgeVersion.judge, JudgeVersion.model)
    )
    return [
        VersionAgreement(
            judge=v.judge,
            model=v.model,
            version=v.content_sha256[:12],
            items=Share.of(sum(by_version[v.id]), len(by_version[v.id])),
        )
        for v in versions
    ]


async def call_agreement(
    session: AsyncSession, by_call: dict[uuid.UUID, list[tuple[Outcome, UnsureKind | None]]]
) -> Share:
    if not by_call:
        return Share.of(0, 0)
    machine = {
        evaluation_id: (found, criteria)
        for evaluation_id, found, criteria in await session.execute(
            select(Evaluation.id, Evaluation.scenario_verdict, func.count(EvaluationItem.id))
            .join(EvaluationItem, EvaluationItem.evaluation_id == Evaluation.id)
            .where(Evaluation.id.in_(by_call), EvaluationItem.item_key.startswith(CRITERION))
            .group_by(Evaluation.id)
        )
    }
    agreed = [
        verdict(given) is machine[evaluation_id][0]
        for evaluation_id, given in by_call.items()
        if len(given) == machine[evaluation_id][1]
    ]
    return Share.of(sum(agreed), len(agreed))
