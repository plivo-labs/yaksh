import asyncio

from yaksha.domain.conversations import CallObserver, CallOutcome, CallRequest, EndReason


class UnavailableCaller:
    """Fails every call with the reason phone calls are off; only conversations queued before
    the worker lost its Plivo setup ever reach it."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        return CallOutcome(connected=False, end_reason=EndReason.ERROR, caller_error=self._reason)
