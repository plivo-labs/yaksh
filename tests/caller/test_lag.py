import asyncio
import time

from yaksh.caller.lag import LagTicker, worse
from yaksh.domain.latency import LoopLag


class Clock:
    def __init__(self) -> None:
        self.now_ms = 0

    def ms(self) -> int:
        return self.now_ms


async def test_a_stall_on_the_event_loop_shows_as_lag_at_the_time_it_ended() -> None:
    lag, clock = LagTicker(), Clock()
    call = lag.watch(clock.ms)
    await asyncio.sleep(0.05)
    clock.now_ms = 7_000
    time.sleep(0.15)  # holds the loop, as loading a model on it does
    await asyncio.sleep(0.01)
    clock.now_ms = 9_000
    await asyncio.sleep(0.05)

    stalled = lag.unwatch(call)

    assert stalled is not None and stalled.max_ms >= 100 and stalled.samples >= 3
    assert stalled.max_at_ms == 7_000


async def test_a_call_that_ended_before_the_ticker_ran_has_no_lag() -> None:
    lag = LagTicker()

    assert lag.unwatch(lag.watch(Clock().ms)) is None


async def test_each_call_gets_the_stalls_of_its_own_time() -> None:
    lag, clock = LagTicker(), Clock()
    first = lag.watch(clock.ms)
    await asyncio.sleep(0.05)
    time.sleep(0.5)  # the loop stalls while only the first call talks
    second = lag.watch(clock.ms)  # the late tick has not run yet
    await asyncio.sleep(0.05)
    clock.now_ms = 10_000  # the second call ends
    await asyncio.sleep(0.05)
    clock.now_ms = 20_000
    time.sleep(0.2)  # the loop stalls after the second call ended

    second_lag = lag.unwatch(second, 10_000)
    first_lag = lag.unwatch(first)

    assert first_lag is not None and first_lag.max_ms >= 400
    assert second_lag is not None and second_lag.max_ms < 250 and second_lag.max_at_ms <= 10_000


async def test_a_stall_that_crosses_the_end_of_a_call_counts_for_it() -> None:
    lag, clock = LagTicker(), Clock()
    call = lag.watch(clock.ms)
    await asyncio.sleep(0.05)
    clock.now_ms = 10_000
    time.sleep(0.2)  # the call ends 100 ms before the stall does

    stalled = lag.unwatch(call, 10_000 - 100)

    assert stalled is not None and stalled.max_ms >= 150
    assert lag.unwatch(call) is None


def test_the_worse_of_two_loops_keeps_the_larger_stall_and_percentile() -> None:
    child = LoopLag(max_ms=40, max_at_ms=1_000, p99_ms=25, samples=500)
    worker = LoopLag(max_ms=180, max_at_ms=4_000, p99_ms=12, samples=480)

    assert worse(child, worker) == LoopLag(max_ms=180, max_at_ms=4_000, p99_ms=25, samples=500)
    assert worse(child, None) == child and worse(None, worker) == worker
