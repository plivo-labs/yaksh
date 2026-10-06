from typing import Any

import pytest
from pydantic import SecretStr

from tests.conftest import FakeProvider, response_body
from yaksha.api.app import generation_model
from yaksha.config import Settings
from yaksha.domain.errors import UnavailableError
from yaksha.domain.language_models import ModelCallError
from yaksha.integrations.openai_models import OpenAIJsonModel

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


async def ask(model: OpenAIJsonModel) -> dict[str, Any]:
    try:
        return (
            await model.complete_json(
                system="Be brief.", user="Ready?", name="reply", schema=SCHEMA
            )
        ).data
    finally:
        await model.close()


async def test_the_responses_api_is_asked_for_the_strict_schema(
    provider: tuple[str, FakeProvider],
) -> None:
    base, fake = provider

    answer = await ask(
        OpenAIJsonModel.openai("sk-test", "gpt-4.1", base_url=f"{base}/v1", timeout_s=30)
    )

    path, _, body = fake.requests[0]
    assert answer == {"answer": "yes"}
    assert path == "/v1/responses"
    assert (body["model"], body["instructions"], body["input"]) == (
        "gpt-4.1",
        "Be brief.",
        "Ready?",
    )
    assert body["text"] == {
        "format": {"type": "json_schema", "name": "reply", "schema": SCHEMA, "strict": True}
    }
    assert body["store"] is False


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
    assert fake.requests[0][0] == "/gateway/v1/responses"


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ((200, response_body("", refusal="I can't help with that.")), "the model refused"),
        ((200, response_body("not json")), "the model's answer is not JSON"),
        ((200, response_body("[1, 2]")), "the model's answer is not a JSON object"),
        (
            (200, response_body('{"answer": "ye"', incomplete="max_output_tokens")),
            r"cut short \(max_output_tokens\)",
        ),
        (
            (200, response_body('{"answer": "no"}', incomplete="content_filter")),
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
            (
                await model.complete_json(
                    system="Be brief.", user=user, name="reply", schema=SCHEMA
                )
            ).data
            for user in ("Ready?", "Still ready?")
        ]
    finally:
        await model.close()

    check, *calls = [body for _, _, body in fake.requests]
    assert answers == [{"answer": "yes"}] * 2
    assert check["reasoning"] == {"effort": "xhigh"} and "text" not in check
    assert [call.get("reasoning") for call in calls] == [
        {"effort": "xhigh"} if reasoning else None
    ] * 2


async def test_a_reasoning_check_that_fails_is_asked_again_on_the_next_call(
    provider: tuple[str, FakeProvider],
) -> None:
    base, fake = provider
    fake.outages = 1
    model = OpenAIJsonModel.openai(
        "sk-test", "gpt-6-luna", base_url=f"{base}/v1", timeout_s=30, reasoning_effort="xhigh"
    )

    try:
        for user in ("Ready?", "Still ready?"):
            await model.complete_json(system="Be brief.", user=user, name="reply", schema=SCHEMA)
    finally:
        await model.close()

    assert fake.efforts() == ["xhigh", None, "xhigh", "xhigh"]


async def test_an_answer_names_its_model_and_tokens_and_a_failure_says_if_it_can_pass(
    provider: tuple[str, FakeProvider],
) -> None:
    base, fake = provider

    def model() -> OpenAIJsonModel:
        return OpenAIJsonModel.openai(
            "sk-test", "gpt-4.1", base_url=f"{base}/v1", timeout_s=30, retries=0
        )

    first = model()
    try:
        answer = await first.complete_json(
            system="Be brief.", user="Ready?", name="reply", schema=SCHEMA
        )
    finally:
        await first.close()
    temporary = {}
    for status in (429, 503, 404, 400):
        fake.reply = (status, {"error": {"message": "no", "type": "x"}})
        with pytest.raises(ModelCallError) as raised:
            await ask(model())
        temporary[status] = raised.value.temporary

    assert (answer.model, answer.input_tokens, answer.output_tokens) == ("gpt-4.1", 12, 3)
    assert temporary == {429: True, 503: True, 404: False, 400: False}
