"""A run's verdict numbers: the pass rate as a mean over scenarios, so a scenario with more calls
does not count more; coverage and the worst-to-best range when some calls were not scored; the
"this suite" interval from the scenarios' own results; and pass^k, the chance that k repeats of
a scenario all pass."""

import functools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from yaksh.domain.evaluations import Verdict

DRAWS = 4_000
MIN_INTERVAL_SCENARIOS = 5


@dataclass(frozen=True)
class ScenarioResults:
    """The judged calls of one scenario: each repeat's verdict, None when its evaluation
    failed."""

    verdicts: Sequence[Verdict | None]

    @property
    def passes(self) -> int:
        return sum(verdict is Verdict.PASS for verdict in self.verdicts)

    @property
    def scored(self) -> int:
        return sum(verdict in (Verdict.PASS, Verdict.FAIL) for verdict in self.verdicts)

    @property
    def unscored(self) -> int:
        return len(self.verdicts) - self.scored


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def pass_rate(scenarios: Sequence[ScenarioResults]) -> float | None:
    """The mean over scenarios with a scored call of each one's passes over its scored calls."""
    return mean([s.passes / s.scored for s in scenarios if s.scored])


def coverage(scenarios: Sequence[ScenarioResults]) -> float | None:
    calls = sum(len(s.verdicts) for s in scenarios)
    return sum(s.scored for s in scenarios) / calls if calls else None


def worst_and_best(scenarios: Sequence[ScenarioResults]) -> tuple[float, float] | None:
    """The pass rate with every unscored call counted as a fail, and as a pass."""
    counted = [s for s in scenarios if s.verdicts]
    if not counted:
        return None
    worst = [s.passes / len(s.verdicts) for s in counted]
    best = [(s.passes + s.unscored) / len(s.verdicts) for s in counted]
    return sum(worst) / len(worst), sum(best) / len(best)


def suite_interval(scenarios: Sequence[ScenarioResults], seed: int) -> tuple[float, float] | None:
    """The 95% interval of the pass rate, from random draws of each scenario's rate (Jeffreys:
    beta(passes + 1/2, fails + 1/2)). The seed, the run's, makes the same run always give the
    same interval. None below five scenarios: too few to say."""
    return interval(tuple((s.passes, s.scored) for s in scenarios if s.scored), seed)


@functools.lru_cache(maxsize=256)
def interval(scored: tuple[tuple[int, int], ...], seed: int) -> tuple[float, float] | None:
    """Cached: the run page asks for the same numbers on every poll."""
    if len(scored) < MIN_INTERVAL_SCENARIOS:
        return None
    draws = random.Random(seed)
    means = sorted(
        sum(draws.betavariate(passes + 0.5, total - passes + 0.5) for passes, total in scored)
        / len(scored)
        for _ in range(DRAWS)
    )
    return means[int(0.025 * DRAWS)], means[int(0.975 * DRAWS) - 1]


def pass_hat_k(scenarios: Sequence[ScenarioResults], k: int = 2) -> tuple[float | None, int]:
    """The mean over scenarios with at least k scored calls of C(passes, k) / C(scored, k), and
    how many scenarios that is."""
    counted = [math.comb(s.passes, k) / math.comb(s.scored, k) for s in scenarios if s.scored >= k]
    return mean(counted), len(counted)


def inconsistent(scenarios: Sequence[ScenarioResults]) -> list[int]:
    """The scenarios, by index, that both passed and failed across repeats."""
    return [
        index
        for index, s in enumerate(scenarios)
        if Verdict.PASS in s.verdicts and Verdict.FAIL in s.verdicts
    ]
