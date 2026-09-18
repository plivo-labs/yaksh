"""Workers that cannot stop cleanly, for the process-exit tests.

Run as `python -m tests.stuck_workers <kind> <database url> <data dir>`.
"""

import asyncio
import contextlib
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from truman.__main__ import run_worker
from truman.caller.plivo_server import StreamRegistry
from truman.caller.stub import StubCaller
from truman.config import Settings
from truman.domain.conversations import (
    Caller,
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    WireEvent,
    WireEventKind,
)
from truman.simulation import conversations
from truman.worker import worker as worker_module


async def stuck(*args: Any, **kwargs: Any) -> Any:
    while True:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)


class Immortal:
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=0))
        return await stuck()


class HoldsUntilStop:
    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=0))
        await stop.wait()
        return CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST)


def immortal() -> Caller:
    return Immortal()


def stuck_write() -> Caller:
    conversations.finalize = stuck
    worker_module.FINALIZE_TIMEOUT_S = 1
    return HoldsUntilStop()


def stuck_disposal() -> Caller:
    AsyncEngine.dispose = stuck
    return StubCaller()


KINDS = {"immortal": immortal, "stuck_write": stuck_write, "stuck_disposal": stuck_disposal}

if __name__ == "__main__":
    kind, database_url, data_dir = sys.argv[1:]
    settings = Settings.model_validate(
        {
            "api_token": "t",
            "database_url": database_url,
            "data_dir": data_dir,
            "worker_poll_interval_s": 0.05,
            "worker_heartbeat_s": 0.05,
            "worker_lease_s": 2,
            "end_timeout_s": 0.3,
        }
    )
    asyncio.run(run_worker(settings, KINDS[kind](), StreamRegistry(), None))
