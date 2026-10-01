import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from pydantic import SecretStr

from truman.api.app import generation_model
from truman.caller.plivo_server import PlivoServer
from truman.config import Settings
from truman.domain.errors import UnavailableError
from truman.integrations.openai_models import OpenAIJsonModel

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def completion(
    content: str | None, refusal: str | None = None, finish_reason: str = "stop"
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4.1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    }


UNSUPPORTED = {
    "error": {
        "message": "Unsupported parameter: 'reasoning_effort' is not supported with this model.",
        "type": "invalid_request_error",
        "code": "unsupported_parameter",
    }
}


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        self.reply: tuple[int, dict[str, Any]] = (200, completion('{"answer": "yes"}'))
        self.reasoning = True
        """Whether the model takes reasoning_effort; gpt-4.1 refuses it with a 400."""


@pytest.fixture
async def provider() -> AsyncIterator[tuple[str, FakeProvider]]:
    fake = FakeProvider()
    app = FastAPI()

    @app.post("/{path:path}")
    async def chat(path: str, request: Request) -> Response:
        sent = await request.json()
        fake.requests.append((f"/{path}", dict(request.query_params), sent))
        if not fake.reasoning and "reasoning_effort" in sent:
            return Response(json.dumps(UNSUPPORTED), status_code=400, media_type="application/json")
        status, body = fake.reply
        return Response(json.dumps(body), status_code=status, media_type="application/json")

    server = PlivoServer(app, port=0)
    await server.start()
    yield f"http://127.0.0.1:{server.port}", fake
    await server.stop(2.0)


async def ask(model: OpenAIJsonModel) -> dict[str, Any]:
    try:
        return await model.complete_json(
            system="Be brief.", user="Ready?", name="reply", schema=SCHEMA
        )
    finally:
        await model.close()


async def test_openai_is_asked_for_the_strict_schema(
    provider: tuple[str, FakeProvider],
) -> None:
    base, fake = provider

    answer = await ask(
        OpenAIJsonModel.openai("sk-test", "gpt-4.1", base_url=f"{base}/v1", timeout_s=30)
    )

    path, _, body = fake.requests[0]
    assert answer == {"answer": "yes"}
    assert path == "/v1/chat/completions"
    assert body["model"] == "gpt-4.1"
    assert body["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Ready?"},
    ]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "reply", "schema": SCHEMA, "strict": True},
    }


async def test_scenario_generation_asks_the_configured_openai_base_url(
    provider: tuple[str, FakeProvider], settings: Settings
) -> None:
    base, fake = provider
    configured = settings.model_copy(
        update={
            "openai_api_key": SecretStr("sk-test"),
            "openai_base_url": f"{base}/gateway/v1",
        }
    )

    model = generation_model(configured)
    assert isinstance(model, OpenAIJsonModel)
    answer = await ask(model)

    assert answer == {"answer": "yes"}
    assert fake.requests[0][0] == "/gateway/v1/chat/completions"


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ((200, completion(None, refusal="I can't help with that.")), "the model refused"),
        ((200, completion("not json")), "the model's answer is not JSON"),
        ((200, completion("[1, 2]")), "the model's answer is not a JSON object"),
        ((200, completion('{"answer": "ye"}', finish_reason="length")), r"cut short \(length\)"),
        (
            (200, completion('{"answer": "no"}', finish_reason="content_filter")),
            r"cut short \(content_filter\)",
        ),
        (
            (400, {"error": {"message": "bad schema", "type": "invalid_request_error"}}),
            "the model call failed: HTTP 400 invalid_request_error",
        ),
    ],
    ids=["refusal", "not json", "not an object", "too long", "filtered", "rejected"],
)
async def test_unusable_answers_are_reported_as_unavailable(
    provider: tuple[str, FakeProvider], reply: tuple[int, dict[str, Any]], message: str
) -> None:
    base, fake = provider
    fake.reply = reply

    with pytest.raises(UnavailableError, match=message):
        await ask(OpenAIJsonModel.openai("sk-test", "gpt-4.1", base_url=f"{base}/v1", timeout_s=30))


async def test_a_failure_message_never_repeats_the_providers_response(
    provider: tuple[str, FakeProvider],
) -> None:
    base, fake = provider
    fake.reply = (
        401,
        {
            "error": {
                "message": "Incorrect API key provided: sk-secret-123",
                "code": "invalid_api_key",
            }
        },
    )

    with pytest.raises(UnavailableError) as raised:
        await ask(
            OpenAIJsonModel.openai("sk-secret-123", "gpt-4.1", base_url=f"{base}/v1", timeout_s=30)
        )

    assert str(raised.value) == "the model call failed: HTTP 401 invalid_api_key"


@pytest.mark.parametrize("reasoning", [True, False])
async def test_the_reasoning_effort_goes_with_every_call_only_when_the_model_takes_it(
    provider: tuple[str, FakeProvider], reasoning: bool
) -> None:
    base, fake = provider
    fake.reasoning = reasoning
    model = OpenAIJsonModel.openai(
        "sk-test", "gpt-6-luna", base_url=f"{base}/v1", timeout_s=30, reasoning_effort="xhigh"
    )

    try:
        answers = [
            await model.complete_json(system="Be brief.", user=user, name="reply", schema=SCHEMA)
            for user in ("Ready?", "Still ready?")
        ]
    finally:
        await model.close()

    check, *calls = [body for _, _, body in fake.requests]
    assert answers == [{"answer": "yes"}] * 2
    assert check["reasoning_effort"] == "xhigh" and "response_format" not in check
    assert [call.get("reasoning_effort") for call in calls] == ["xhigh" if reasoning else None] * 2
