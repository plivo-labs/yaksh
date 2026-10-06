import asyncio
import time

from yaksha.caller.lag import LagSampler


class Clock:
    def __init__(self) -> None:
        self.now_ms = 0

    def ms(self) -> int:
        return self.now_ms


async def test_a_stall_on_the_event_loop_shows_as_lag_at_the_time_it_ended() -> None:
    clock = Clock()
    sampler = LagSampler(clock.ms)
    await asyncio.sleep(0.05)
    clock.now_ms = 7_000
    time.sleep(0.15)  # holds the loop, as loading a model on it does
    await asyncio.sleep(0.01)
    clock.now_ms = 9_000
    await asyncio.sleep(0.05)

    lag = sampler.stop()

    assert lag is not None and lag.max_ms >= 100 and lag.samples >= 3
    assert lag.max_at_ms == 7_000


async def test_a_call_that_ended_before_the_sampler_ran_has_no_lag() -> None:
    assert LagSampler(Clock().ms).stop() is None
