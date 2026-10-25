import pytest

from yaksh.domain.evaluations import GateNumbers
from yaksh.domain.runs import RunStatus
from yaksh.domain.suites import RunResult, run_result, suite_result

DONE, CANCELLED = RunStatus.DONE, RunStatus.CANCELLED


def numbers(
    passed: int = 0,
    failed: int = 0,
    not_scored: int = 0,
    *,
    pending: int = 0,
    unplayed_passed: int = 0,
    unplayed_failed: int = 0,
    unplayed_not_scored: int = 0,
) -> GateNumbers:
    """The numbers of a run of one scenario with these calls."""
    calls = passed + failed + not_scored
    scored = passed + failed
    return GateNumbers(
        pending=pending,
        passed=passed,
        failed=failed,
        not_scored=not_scored,
        pass_rate=passed / scored if scored else None,
        coverage=scored / calls if calls else None,
        worst=passed / calls if calls else None,
        best=(passed + not_scored) / calls if calls else None,
        unplayed_passed=unplayed_passed,
        unplayed_failed=unplayed_failed,
        unplayed_not_scored=unplayed_not_scored,
    )


@pytest.mark.parametrize(
    ("status", "found", "percent", "result"),
    [
        (RunStatus.RUNNING, numbers(1, 0, 0, pending=1), 80, RunResult.RUNNING),
        (DONE, numbers(1, 0, 0, pending=1), 80, RunResult.JUDGING),
        (CANCELLED, numbers(1, 0, 0, pending=1), 80, RunResult.JUDGING),
        (CANCELLED, numbers(1, 0, 0), 80, RunResult.CANCELLED),
        (DONE, numbers(19, 0, 1), 95, RunResult.PASSED),
        (DONE, numbers(18, 1, 1), 95, RunResult.FAILED),
        (DONE, numbers(4, 1, 0), 80, RunResult.PASSED),
        (DONE, numbers(4, 1, 1), 80, RunResult.NOT_DECIDED),
        (DONE, numbers(4, 1, 1), 60, RunResult.PASSED),
        (DONE, numbers(4, 1, 1), 90, RunResult.FAILED),
        (DONE, numbers(1, 0, 1), 100, RunResult.NOT_DECIDED),
        (DONE, numbers(0, 0, 2), 50, RunResult.NOT_DECIDED),
        (DONE, numbers(unplayed_passed=2), 80, RunResult.PASSED),
        (DONE, numbers(unplayed_passed=1, unplayed_failed=1), 80, RunResult.FAILED),
        (DONE, numbers(5, 0, 0, unplayed_not_scored=1), 80, RunResult.FAILED),
    ],
    ids=[
        "running",
        "judges at work",
        "a cancelled run waits for its judges",
        "cancelled",
        "coverage of exactly 0.95: the pass rate decides",
        "coverage of 0.95 below the rate",
        "a pass rate equal to the rate",
        "the rate is between worst and best",
        "a worst rate that reaches the rate",
        "a best rate below the rate",
        "a best rate equal to the rate",
        "no call scored",
        "only voicemail calls, all passed",
        "a voicemail call failed",
        "a voicemail call with no verdict",
    ],
)
def test_a_run_gets_the_first_result_that_applies(
    status: RunStatus, found: GateNumbers, percent: int, result: RunResult
) -> None:
    assert run_result(status, found, percent) is result


@pytest.mark.parametrize(
    ("results", "result"),
    [
        ([RunResult.FAILED, RunResult.RUNNING], RunResult.RUNNING),
        ([RunResult.FAILED, RunResult.JUDGING], RunResult.JUDGING),
        ([RunResult.CANCELLED, RunResult.FAILED], RunResult.FAILED),
        ([RunResult.CANCELLED, RunResult.PASSED], RunResult.CANCELLED),
        ([RunResult.NOT_DECIDED, RunResult.PASSED], RunResult.NOT_DECIDED),
        ([RunResult.PASSED, RunResult.PASSED], RunResult.PASSED),
    ],
)
def test_a_suite_run_waits_for_every_run_and_puts_a_failure_before_a_cancel(
    results: list[RunResult], result: RunResult
) -> None:
    assert suite_result(results) is result
