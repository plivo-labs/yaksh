import asyncio
import time

from truman.domain.conversations import (
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    Provenance,
    Role,
    Turn,
    WireEvent,
    WireEventKind,
)


async def stopped(stop: asyncio.Event, delay_s: float) -> bool:
    try:
        await asyncio.wait_for(stop.wait(), delay_s)
    except TimeoutError:
        return False
    return True


STUB_NUMBER = "+15550100000"


class StubCaller:
    """Plays a canned conversation without audio or providers, for API and UI development."""

    def __init__(self, *, connect_delay_s: float = 0.2, turn_delay_s: float = 0.5) -> None:
        self.connect_delay_s = connect_delay_s
        self.turn_delay_s = turn_delay_s

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        started = time.monotonic()

        def now_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        observer.wire_event(WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=now_ms()))
        if await stopped(stop, self.connect_delay_s):
            return CallOutcome(connected=False, end_reason=EndReason.USER_REQUEST)
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=now_ms()))

        script: list[tuple[Role, str]] = []
        if request.agent.agent_speaks_first:
            script.append((Role.AGENT, "Hello, thanks for calling. How can I help?"))
        script += [
            (Role.CALLER, request.persona_prompt),
            (Role.AGENT, "Understood. Is there anything else?"),
            (Role.CALLER, "No, that is all. Goodbye."),
        ]
        for role, text in script:
            if await stopped(stop, self.turn_delay_s):
                return CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST)
            spoke_at = now_ms()
            observer.turn(
                Turn(
                    role=role,
                    text=text,
                    started_at_ms=spoke_at,
                    ended_at_ms=spoke_at,
                    provenance=Provenance.TRANSMITTED if role is Role.CALLER else None,
                )
            )
        observer.wire_event(WireEvent(kind=WireEventKind.STOP, at_ms=now_ms()))
        return CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
