"""From item outcomes to one verdict, the same way everywhere."""

from collections.abc import Iterable

from truman.domain.evaluations import Outcome, UnsureKind, Verdict

NOT_SCORED = frozenset({Outcome.UNSURE, Outcome.BLOCKED, Outcome.ERROR, Outcome.PENDING})


def verdict(outcomes: Iterable[tuple[Outcome, UnsureKind | None]]) -> Verdict:
    """Any fail fails. Else any item that could not be scored leaves the whole not scored. Else
    any pass passes. An unsure item whose answer needs a hidden action counts as not applicable,
    and nothing but not-applicable items is not scored."""
    counted = [
        Outcome.NOT_APPLICABLE
        if outcome is Outcome.UNSURE and kind is UnsureKind.HIDDEN_ACTION
        else outcome
        for outcome, kind in outcomes
    ]
    if Outcome.FAIL in counted:
        return Verdict.FAIL
    if NOT_SCORED.intersection(counted):
        return Verdict.NOT_SCORED
    if Outcome.PASS in counted:
        return Verdict.PASS
    return Verdict.NOT_SCORED
