import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request, Response
from openai import AsyncOpenAI
from pydantic import SecretStr

from tests.conftest import APP_SETTINGS, CALLER, Observer, make_settings
from yaksh.caller.plivo_server import PlivoServer
from yaksh.caller.text import NO_WORDS, TextCaller, TextConversation
from yaksh.domain.agents import AgentConfig, Transport
from yaksh.domain.conversations import CallOutcome, CallRequest, EndReason, Role, WireEventKind
from yaksh.domain.scenarios import Fact
from yaksh.integrations.text_agent import TextAgent

BRIEF = "Books cleanings and checkups for the patients of Maple Dental."
TOKEN = "sk_text_secret"
Reply = tuple[int, Any] | Callable[[dict[str, Any]], Any]


@dataclass
class FakeAgent:
    """A text agent the tests script: one reply for each turn request, in order."""

    url: str
    replies: list[Reply] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    closes: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)


@pytest.fixture
async def agent() -> AsyncIterator[FakeAgent]:
    app = FastAPI()
    fake = FakeAgent(url="")

    @app.post("/turn")
    async def turn(request: Request) -> Response:
        body = await request.json()
        fake.headers.append(dict(request.headers))
        if body.get("status") == "ended":
            fake.closes.append(body)
            return Response(status_code=200)
        fake.turns.append(body)
        reply = fake.replies.pop(0)
        if callable(reply):
            reply = await reply(body)
        status, content = reply
        text = content if isinstance(content, str) else json.dumps(content)
        return Response(text, status_code=status, media_type="application/json")

    server = PlivoServer(app, port=0)
    await server.start()
    fake.url = f"http://127.0.0.1:{server.port}/turn"
    yield fake
    await server.stop(2.0)


class FakeModel:
    """The caller's model: each reply is words, and an end_call reason when it ends the call."""

    def __init__(self, *replies: tuple[str, str | None]) -> None:
        self._replies = list(replies)
        self.inputs: list[list[Any]] = []
        self.efforts: list[Any] = []
        self.responses = SimpleNamespace(create=self._create)

    async def _create(self, **request: Any) -> Any:
        self.inputs.append(list(request["input"]))
        self.efforts.append(request.get("extra_body", {}).get("reasoning"))
        words, ended = self._replies.pop(0)
        output = (
            []
            if ended is None
            else [SimpleNamespace(type="function_call", arguments=json.dumps({"reason": ended}))]
        )
        return SimpleNamespace(output_text=words, output=output, usage=None)


def request(**agent: Any) -> CallRequest:
    config = AgentConfig.model_validate(
        {"endpoint": {"url": "http://unused"}, "brief": BRIEF, **agent}
    )
    return CallRequest(
        conversation_id=uuid.uuid4(),
        agent=config,
        transport=Transport.TEXT,
        **CALLER,
        caller_number=None,
        max_duration_s=120,
        app_settings=APP_SETTINGS,
        caller=APP_SETTINGS.caller,
        agent_data=[Fact(name="Patient name", value="Ananya")],
    )


def said(text: str, **reply: Any) -> tuple[int, dict[str, Any]]:
    return 200, {"messages": [{"role": "assistant", "content": text}], **reply}


async def converse(
    fake: FakeAgent,
    model: FakeModel,
    call: CallRequest | None = None,
    stop: asyncio.Event | None = None,
) -> tuple[CallOutcome, Observer]:
    call = call or request()
    observer = Observer()
    text_agent = TextAgent(
        fake.url,
        {"Authorization": f"Bearer {TOKEN}"},
        (TOKEN,),
        conversation_id=str(call.conversation_id),
        allow_private=True,
    )
    conversation = TextConversation(
        call, observer, stop or asyncio.Event(), text_agent, cast(AsyncOpenAI, model)
    )
    try:
        return await conversation.run(close_s=2), observer
    finally:
        await text_agent.aclose()


async def test_the_agents_session_id_comes_back_on_each_turn_and_the_session_is_closed(
    agent: FakeAgent,
) -> None:
    agent.replies = [
        (200, {"sessionId": "s-42", "messages": [{"role": "assistant", "content": "Hi, Maple."}]}),
        (
            200,
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "find_slots", "arguments": '{"day":"Fri"}'},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "c1", "content": '{"slots":["10:00"]}'},
                    {"role": "assistant", "content": "10 AM Friday?"},
                    {"role": "system", "content": "ignored"},
                ],
                "trace": "an unknown field",
            },
        ),
        said("Bye!"),
    ]
    model = FakeModel(("I'd like a cleaning.", None), ("Okay, thanks. Bye.", "the slot is fine"))

    outcome, observer = await converse(agent, model)

    first, second, last = agent.turns
    assert first == {"message": "", "modality": "audio", "customData": {"Patient name": "Ananya"}}
    assert second == {"sessionId": "s-42", "message": "I'd like a cleaning."}
    assert last == {"sessionId": "s-42", "message": "Okay, thanks. Bye."}
    assert agent.closes == [{"sessionId": "s-42", "status": "ended", "reason": "caller_hangup"}]
    assert agent.headers[0]["yaksh-contract"] == "1"
    assert agent.headers[0]["authorization"] == f"Bearer {TOKEN}"
    assert outcome.connected and outcome.end_reason is EndReason.CALLER_HANGUP
    assert outcome.caller_reason == "the slot is fine"
    assert outcome.caller_settings is not None and outcome.caller_settings.stt_model is None
    connected = next(e for e in observer.events if e.kind is WireEventKind.CONNECTED)
    assert connected.detail == "s-42"
    assert [(turn.role, turn.text) for turn in observer.turns] == [
        (Role.AGENT, "Hi, Maple."),
        (Role.CALLER, "I'd like a cleaning."),
        (Role.AGENT, "10 AM Friday?"),
        (Role.CALLER, "Okay, thanks. Bye."),
        (Role.AGENT, "Bye!"),
    ]
    (tool,) = observer.turns[2].tools
    assert (tool.name, tool.arguments, tool.output) == (
        "find_slots",
        '{"day":"Fri"}',
        '{"slots":["10:00"]}',
    )
    assert model.inputs[0] == [{"role": "user", "content": "Hi, Maple."}]


async def test_a_caller_who_speaks_first_sends_its_first_words_and_the_agent_ends_the_call(
    agent: FakeAgent,
) -> None:
    agent.replies = [said("Maple Dental, how can I help?", sessionId="s-1")]
    agent.replies.append(said("Booked. Goodbye.", status="ended"))
    model = FakeModel(("A cleaning, please.", None))

    outcome, observer = await converse(agent, model, request(agent_speaks_first=False))

    assert agent.turns[0]["message"] == CALLER["first_words"]
    assert observer.turns[0].scripted
    assert outcome.end_reason is EndReason.AGENT_HANGUP
    assert agent.closes == []
    assert model.efforts == [{"effort": "low"}], "the phone caller's effort"
    assert outcome.caller_settings and outcome.caller_settings.reasoning_effort == "low"


async def test_a_refused_start_is_not_tried_again_and_a_missing_session_id_is_an_error(
    agent: FakeAgent,
) -> None:
    agent.replies = [(401, {"error": f"bad token {TOKEN}"})]
    refused, _ = await converse(agent, FakeModel())
    agent.replies = [said("Hello.")]
    unnamed, _ = await converse(agent, FakeModel())

    assert not refused.connected and refused.end_reason is EndReason.START_REFUSED
    assert refused.caller_error == 'HTTP 401: {"error": "bad token [secret]"}'
    assert not unnamed.connected and unnamed.end_reason is EndReason.ERROR
    assert unnamed.caller_error is not None and "sessionId" in unnamed.caller_error
    assert agent.closes == []


async def test_a_lost_session_fails_the_conversation_with_no_close(agent: FakeAgent) -> None:
    agent.replies = [said("Hello.", sessionId="s-1"), (410, {"error": "unknown session"})]

    outcome, _ = await converse(agent, FakeModel(("Hi.", None)))

    assert outcome.connected and outcome.end_reason is EndReason.ERROR
    assert outcome.caller_error is not None and "lost the session" in outcome.caller_error
    assert agent.closes == []


async def test_a_silent_agent_gets_two_nudges_then_the_call_ends(agent: FakeAgent) -> None:
    agent.replies = [said("Hello.", sessionId="s-1"), said(""), said(""), said("")]

    outcome, observer = await converse(agent, FakeModel(("Hi, a cleaning please.", None)))

    nudges = [turn for turn in observer.turns if turn.text == CALLER["nudge"]]
    assert len(nudges) == 2 and all(turn.scripted for turn in nudges)
    assert outcome.end_reason is EndReason.AGENT_SILENT
    assert agent.closes[0]["reason"] == "agent_silent"


async def test_a_reply_with_no_words_is_asked_once_more_and_then_fails(agent: FakeAgent) -> None:
    agent.replies = [
        said("Hello.", sessionId="s-1"),
        said("We will call you. Bye.", status="ended"),
    ]
    model = FakeModel(("", None), ("Okay, thanks.", None))

    outcome, _ = await converse(agent, model)

    assert model.inputs[1][-1] == {"role": "developer", "content": NO_WORDS}
    assert agent.turns[-1]["message"] == "Okay, thanks."
    assert outcome.end_reason is EndReason.AGENT_HANGUP

    agent.replies = [said("Hello.", sessionId="s-2")]
    silent, _ = await converse(agent, FakeModel(("", None), ("", None)))

    assert silent.caller_error is not None
    assert "no words and no tool call" in silent.caller_error


async def test_at_the_turn_limit_the_caller_says_goodbye(agent: FakeAgent) -> None:
    agent.replies = [said("Hello.", sessionId="s-1"), said("Which day?"), said("Bye.")]
    call = request().model_copy(update={"max_turns": 1})

    outcome, observer = await converse(agent, FakeModel(("A cleaning.", None)), call)

    assert outcome.end_reason is EndReason.TURN_LIMIT
    assert agent.turns[-1]["message"] == CALLER["goodbye"]
    assert observer.turns[-2].text == CALLER["goodbye"]
    assert agent.closes[0]["reason"] == "turn_limit"


async def test_a_stop_cancels_a_slow_turn_at_once_and_closes_the_session(
    agent: FakeAgent,
) -> None:
    async def slow(_body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        await asyncio.sleep(5)
        return said("Too late.")

    agent.replies = [said("Hello.", sessionId="s-1"), slow]
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.3, stop.set)
    started = time.monotonic()

    outcome, _ = await converse(agent, FakeModel(("Hi.", None)), stop=stop)

    assert time.monotonic() - started < 2
    assert outcome.end_reason is EndReason.USER_REQUEST
    assert agent.closes == [{"sessionId": "s-1", "status": "ended", "reason": "stopped"}]


async def test_a_secret_the_agent_echoes_is_hidden_in_the_transcript(agent: FakeAgent) -> None:
    agent.replies = [said(f"Your token is {TOKEN}.", sessionId="s-1", status="ended")]

    _, observer = await converse(agent, FakeModel())

    assert observer.turns[0].text == "Your token is [secret]."


async def test_an_invalid_reply_ends_the_conversation(agent: FakeAgent) -> None:
    agent.replies = [said("Hello.", sessionId="s-1"), (200, "not json")]
    broken, _ = await converse(agent, FakeModel(("Hi.", None)))
    agent.replies = [said("\ud800", sessionId="s-2")]
    unstorable, _ = await converse(agent, FakeModel())

    assert broken.caller_error is not None and broken.caller_error.startswith("invalid reply")
    assert unstorable.caller_error is not None and unstorable.caller_error.startswith(
        "invalid reply"
    )


async def test_the_caller_fills_header_secrets_and_refuses_a_missing_one(
    agent: FakeAgent, tmp_path: Any
) -> None:
    caller = TextCaller(make_settings(tmp_path, allow_private_hosts=True))
    endpoint = {
        "url": agent.url,
        "headers": [{"name": "Authorization", "value": "Bearer {{secrets.AGENT_TOKEN}}"}],
    }
    missing = await caller.run(request(endpoint=endpoint), Observer(), asyncio.Event())
    secrets = APP_SETTINGS.secrets.model_copy(
        update={"triggers": {"AGENT_TOKEN": SecretStr(TOKEN)}}
    )
    call = request(endpoint=endpoint).model_copy(
        update={"app_settings": APP_SETTINGS.model_copy(update={"secrets": secrets})}
    )
    agent.replies = [(403, {"error": "no"})]
    refused = await caller.run(call, Observer(), asyncio.Event())

    assert missing.end_reason is EndReason.START_REFUSED
    assert missing.caller_error is not None and "AGENT_TOKEN" in missing.caller_error
    assert agent.headers[-1]["authorization"] == f"Bearer {TOKEN}"
    assert refused.end_reason is EndReason.START_REFUSED
