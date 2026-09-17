import asyncio
import uuid
from pathlib import Path

from tests.caller.test_plivo import Observer
from truman.caller.router import TransportRouter
from truman.domain.agents import AgentConfig, Transport
from truman.domain.conversations import CallObserver, CallOutcome, CallRequest, EndReason


class Answering:
    def __init__(self, name: str) -> None:
        self.name = name

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        return CallOutcome(
            connected=True, end_reason=EndReason.AGENT_HANGUP, caller_error=self.name
        )


def request(agent: dict[str, object], tmp_path: Path) -> CallRequest:
    return CallRequest(
        conversation_id=uuid.uuid4(),
        agent=AgentConfig.model_validate(agent),
        persona_prompt="hello",
        caller_number="+15550100000",
        max_duration_s=10,
        output_dir=tmp_path,
    )


async def test_the_router_picks_the_caller_for_the_agent_transport(tmp_path: Path) -> None:
    router = TransportRouter({Transport.PLIVO_WEBSOCKET: Answering("websocket")})
    websocket = request({"websocket_url": "wss://agent.example.com/stream"}, tmp_path)
    phone = request({"transport": "phone", "agent_number": "+14155550100"}, tmp_path)

    served = await router.run(websocket, Observer(), asyncio.Event())
    unserved = await router.run(phone, Observer(), asyncio.Event())

    assert served.caller_error == "websocket"
    assert unserved.connected is False and unserved.end_reason is EndReason.ERROR
    assert unserved.caller_error == "no caller handles the phone transport"
