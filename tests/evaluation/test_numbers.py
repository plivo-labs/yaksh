import pytest

from yaksha.domain.evaluations import Verdict
from yaksha.evaluation.numbers import (
    ScenarioResults,
    coverage,
    inconsistent,
    interval,
    pass_hat_k,
    pass_rate,
    suite_interval,
    worst_and_best,
)

P, F, N = Verdict.PASS, Verdict.FAIL, Verdict.NOT_SCORED
EXAMPLE = [
    ScenarioResults([P, F, P]),
    ScenarioResults([P, P, P]),
    ScenarioResults([F, N, P]),
]


def test_the_worked_example_of_the_plan() -> None:
    assert pass_rate(EXAMPLE) == pytest.approx(0.7222, abs=1e-4)
    assert coverage(EXAMPLE) == pytest.approx(8 / 9)
    worst, best = worst_and_best(EXAMPLE) or (0.0, 0.0)
    assert (round(worst, 3), round(best, 3)) == (0.667, 0.778)
    assert suite_interval(EXAMPLE, seed=7) is None
    rate, counted = pass_hat_k(EXAMPLE)
    assert (round(rate or 0, 3), counted) == (0.444, 3)
    assert inconsistent(EXAMPLE) == [0, 2]


def test_the_suite_interval_needs_five_scenarios_and_is_the_same_for_the_same_run() -> None:
    five = [ScenarioResults([P, P, F])] * 4 + [ScenarioResults([P, P, P])]

    first = suite_interval(five, seed=42)
    interval.cache_clear()
    again = suite_interval(five, seed=42)

    assert first is not None and first == again
    low, high = first
    assert low < (pass_rate(five) or 0) < high
    assert 0 < low < high < 1


def test_failed_evaluations_count_as_unscored_and_an_empty_run_has_no_numbers() -> None:
    failed = [ScenarioResults([P, None])]

    assert (pass_rate(failed), coverage(failed), worst_and_best(failed)) == (
        1.0,
        0.5,
        (0.5, 1.0),
    )
    assert (pass_rate([]), coverage([]), worst_and_best([]), pass_hat_k([])) == (
        None,
        None,
        None,
        (None, 0),
    )
