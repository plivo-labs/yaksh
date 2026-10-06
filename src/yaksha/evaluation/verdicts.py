"""From item outcomes to one verdict, the same way everywhere."""

from collections.abc import Iterable

from yaksha.domain.evaluations import ItemRole, Outcome, UnsureKind, Verdict

CRITERION = "criterion-"
RULE = "rule-"
NOT_SCORED = frozenset({Outcome.UNSURE, Outcome.BLOCKED, Outcome.ERROR, Outcome.PENDING})


def verdict(outcomes: Iterable[tuple[Outcome, UnsureKind | None]]) -> Verdict:
    """Any fail fails. Else any item that could not be scored leaves the whole not scored. Else
    any pass passes. An unsure item whose answer needs a hidden action counts as not applicable,
    and nothing but not-applicable items is not scored."""
    counted = [scored_as(outcome, kind) for outcome, kind in outcomes]
    if Outcome.FAIL in counted:
        return Verdict.FAIL
    if NOT_SCORED.intersection(counted):
        return Verdict.NOT_SCORED
    if Outcome.PASS in counted:
        return Verdict.PASS
    return Verdict.NOT_SCORED


def scored_as(outcome: Outcome, kind: UnsureKind | None) -> Outcome:
    """How a verdict counts an outcome: an unsure item whose answer needs a hidden action as not
    applicable."""
    if outcome is Outcome.UNSURE and kind is UnsureKind.HIDDEN_ACTION:
        return Outcome.NOT_APPLICABLE
    return outcome


def counted(key: str, role: ItemRole, *, criteria_only: bool) -> bool:
    """Whether a verdict counts the item: the scenario verdict counts the criteria, the
    conversation verdict also the agent rules that decide."""
    return key.startswith(CRITERION) or (not criteria_only and role is ItemRole.DECIDING)
