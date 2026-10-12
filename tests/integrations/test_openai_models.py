from typing import Any

import pytest
from pydantic import SecretStr

from tests.conftest import FakeProvider, response_body
from yaksh.api.providers import Providers
from yaksh.domain.errors import UnavailableError
from yaksh.domain.language_models import ModelCallError
from yaksh.domain.settings import AppSettings, Llm, Secrets
from yaksh.integrations.openai_models import OpenAIJsonModel

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


async def test_scenario_generation_follows_the_saved_llm_provider_without_a_restart(
    provider: tuple[str, FakeProvider],
) -> None:
    base, fake = provider
    providers = Providers()
    first = AppSettings(
        llm=Llm(base_url=f"{base}/gateway/v1"), secrets=Secrets(llm_api_key=SecretStr("sk-test"))
    )
    moved = first.model_copy(update={"llm": Llm(base_url=f"{base}/other/v1"), "version": 1})

    model = providers.generation_model(first)
    assert isinstance(model, OpenAIJsonModel)
    assert await ask(model) == {"answer": "yes"}
    moved_model = providers.generation_model(moved)
    assert isinstance(moved_model, OpenAIJsonModel)
    await ask(moved_model)
    await providers.close()

    paths = [request[0] for request in fake.requests]
    assert set(paths) == {"/gateway/v1/responses", "/other/v1/responses"}
    assert paths.index("/other/v1/responses") > max(
        i for i, path in enumerate(paths) if path == "/gateway/v1/responses"
    )


async def test_scenario_generation_is_off_without_a_saved_key() -> None:
    assert Providers().generation_model(AppSettings()) is None


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
