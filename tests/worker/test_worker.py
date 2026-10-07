import asyncio
import contextlib
import time
import uuid

import pytest

from tests.conftest import FakeCaller, FixedSource, make_worker
from yaksha.config import Settings
from yaksha.db.session import create_engine, create_sessionmaker
from yaksha.domain.conversations import EndReason
from yaksha.simulation.calls import LiveCall


async def survives_cancellation() -> bool:
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.sleep(3600)
    await asyncio.sleep(3600)
    return True


async def test_cancelling_the_worker_while_it_abandons_a_stuck_write_marks_it_fatal(
    offline_settings: Settings,
) -> None:
    worker = make_worker(
        create_sessionmaker(create_engine(offline_settings.database_url.encoded_string())),
        FakeCaller(),
        offline_settings,
        worker_id="unit",
        source=FixedSource(),
    )
    write = asyncio.ensure_future(survives_cancellation())
    abandon = asyncio.ensure_future(worker._abandon(write, "write"))
    await asyncio.sleep(0.05)

    abandon.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandon

    assert worker.fatal.is_set()
    write.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await write


async def test_a_poll_that_survives_cancellation_marks_the_worker_fatal(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stuck(*args: object, **kwargs: object) -> int:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)
        await asyncio.sleep(3600)
        return 0

    monkeypatch.setattr("yaksha.simulation.conversations.reap_expired", stuck)
    settings = offline_settings.model_copy(update={"end_timeout_s": 0.1})
    worker = make_worker(
        create_sessionmaker(create_engine(settings.database_url.encoded_string())),
        FakeCaller(),
        settings,
        worker_id="unit",
        source=FixedSource(),
    )
    stop = asyncio.Event()
    run = asyncio.ensure_future(worker.run(stop))
    await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(run, timeout=2)

    assert worker.fatal.is_set()


async def test_a_renewal_that_survives_cancellation_stops_the_call_and_marks_fatal(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stuck(*args: object, **kwargs: object) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)
        await asyncio.sleep(3600)

    monkeypatch.setattr("yaksha.simulation.conversations.renew_lease", stuck)
    settings = offline_settings.model_copy(
        update={"worker_lease_s": 0.2, "worker_heartbeat_s": 0.02, "end_timeout_s": 0.1}
    )
    worker = make_worker(
        create_sessionmaker(create_engine(settings.database_url.encoded_string())),
        FakeCaller(),
        settings,
        worker_id="unit",
        source=FixedSource(),
    )
    live = LiveCall()

    await asyncio.wait_for(worker._maintain(uuid.uuid4(), live, time.monotonic()), timeout=2)

    assert live.stop.is_set() and live.end_reason is EndReason.LEASE_LOST
    assert worker.fatal.is_set()


async def test_cancelling_maintenance_during_a_stuck_renewal_abandons_it(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stuck(*args: object, **kwargs: object) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)
        await asyncio.sleep(3600)

    monkeypatch.setattr("yaksha.simulation.conversations.renew_lease", stuck)
    settings = offline_settings.model_copy(
        update={"worker_lease_s": 5, "worker_heartbeat_s": 0.02, "end_timeout_s": 0.1}
    )
    worker = make_worker(
        create_sessionmaker(create_engine(settings.database_url.encoded_string())),
        FakeCaller(),
        settings,
        worker_id="unit",
        source=FixedSource(),
    )
    maintenance = asyncio.ensure_future(
        worker._maintain(uuid.uuid4(), LiveCall(), time.monotonic())
    )
    await asyncio.sleep(0.1)

    assert await worker._abandon(maintenance, "maintenance", timeout=0.3) is True
    assert worker.fatal.is_set()


async def test_the_lease_is_measured_from_when_a_renewal_was_sent(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    async def slow_then_stuck(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(0.6)
            return "running"
        await asyncio.sleep(3600)

    monkeypatch.setattr("yaksha.simulation.conversations.renew_lease", slow_then_stuck)
    settings = offline_settings.model_copy(
        update={"worker_lease_s": 1.0, "worker_heartbeat_s": 0.05, "end_timeout_s": 0.1}
    )
    worker = make_worker(
        create_sessionmaker(create_engine(settings.database_url.encoded_string())),
        FakeCaller(),
        settings,
        worker_id="unit",
        source=FixedSource(),
    )
    live = LiveCall()
    started = time.monotonic()

    await asyncio.wait_for(worker._maintain(uuid.uuid4(), live, started), timeout=3)

    assert live.stop.is_set() and live.end_reason is EndReason.LEASE_LOST
    assert time.monotonic() - started < 1.4


async def test_a_stalled_poll_is_cancelled_and_retried_without_a_shutdown_signal(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    async def stalled(*args: object, **kwargs: object) -> int:
        calls["n"] += 1
        await asyncio.sleep(3600)
        return 0

    monkeypatch.setattr("yaksha.simulation.conversations.reap_expired", stalled)
    settings = offline_settings.model_copy(
        update={"worker_lease_s": 0.2, "worker_poll_interval_s": 0.02, "end_timeout_s": 0.1}
    )
    worker = make_worker(
        create_sessionmaker(create_engine(settings.database_url.encoded_string())),
        FakeCaller(),
        settings,
        worker_id="unit",
        source=FixedSource(),
    )
    stop = asyncio.Event()
    run = asyncio.ensure_future(worker.run(stop))
    deadline = asyncio.get_running_loop().time() + 3
    while calls["n"] < 2:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)

    stop.set()
    await asyncio.wait_for(run, timeout=2)

    assert not worker.fatal.is_set()
