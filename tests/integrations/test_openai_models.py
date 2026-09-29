import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response

from truman.caller.plivo_server import PlivoServer
from truman.domain.errors import UnavailableError
from truman.integrations.openai_models import AZURE_API_VERSION, OpenAIJsonModel

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


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        self.reply: tuple[int, dict[str, Any]] = (200, completion('{"answer": "yes"}'))


@pytest.fixture
async def provider() -> AsyncIterator[tuple[str, FakeProvider]]:
    fake = FakeProvider()
    app = FastAPI()

    @app.post("/{path:path}")
    async def chat(path: str, request: Request) -> Response:
        fake.requests.append((f"/{path}", dict(request.query_params), await request.json()))
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

    answer = await ask(OpenAIJsonModel.openai("sk-test", "gpt-4.1", base_url=f"{base}/v1"))

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


async def test_azure_is_asked_through_its_deployment(provider: tuple[str, FakeProvider]) -> None:
    base, fake = provider

    answer = await ask(OpenAIJsonModel.azure(base, "azure-key", "scenario-writer"))

    path, query, _ = fake.requests[0]
    assert answer == {"answer": "yes"}
    assert path == "/openai/deployments/scenario-writer/chat/completions"
    assert query == {"api-version": AZURE_API_VERSION}


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
        await ask(OpenAIJsonModel.openai("sk-test", "gpt-4.1", base_url=f"{base}/v1"))


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
        await ask(OpenAIJsonModel.openai("sk-secret-123", "gpt-4.1", base_url=f"{base}/v1"))

    assert str(raised.value) == "the model call failed: HTTP 401 invalid_api_key"
