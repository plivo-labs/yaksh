import asyncio
import time

from truman.caller.lag import LagSampler


async def test_a_stall_on_the_event_loop_shows_as_lag() -> None:
    sampler = LagSampler()
    await asyncio.sleep(0.05)
    time.sleep(0.15)  # holds the loop, as loading a model on it does
    await asyncio.sleep(0.05)

    lag = sampler.stop()

    assert lag is not None and lag.max_ms >= 100 and lag.samples >= 3


async def test_a_call_that_ended_before_the_sampler_ran_has_no_lag() -> None:
    assert LagSampler().stop() is None
