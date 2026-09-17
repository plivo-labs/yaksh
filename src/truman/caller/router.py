"""One caller per transport, chosen from the agent configuration a conversation pinned."""

import asyncio
from collections.abc import Mapping

from truman.domain.agents import Transport
from truman.domain.conversations import Caller, CallObserver, CallOutcome, CallRequest, EndReason


class TransportRouter:
    def __init__(self, callers: Mapping[Transport, Caller]) -> None:
        self._callers = dict(callers)

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        caller = self._callers.get(request.agent.transport)
        if caller is None:
            return CallOutcome(
                connected=False,
                end_reason=EndReason.ERROR,
                caller_error=f"no caller handles the {request.agent.transport.value} transport",
            )
        return await caller.run(request, observer, stop)
