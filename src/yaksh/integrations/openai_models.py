"""Structured JSON answers from the Responses API of OpenAI or a compatible service, for
generating test scenarios and for judging calls."""

import asyncio
import json
import logging
from typing import Any

import openai
from openai import AsyncOpenAI, omit
from openai.types.responses import Response
from pipecat.services.openai.responses.llm import _THINKING_DEFAULTS, _model_name

from yaksh.domain.language_models import ModelAnswer, ModelCallError

log = logging.getLogger(__name__)

RETRIES = 1
"""One retry: someone is waiting for the answer in the console."""
CHECK_TIMEOUT_S = 15.0
"""For one try of the reasoning check, which takes about a second even at the highest effort."""


def caller_effort(model: str, configured: str | None) -> str | None:
    """The effort the caller sends: the configured one, else low for a model that Pipecat lists,
    or the model's lowest effort when that is above low. A model that Pipecat does not list gets
    none: a model without reasoning refuses any."""
    if configured:
        return configured
    lowest = _THINKING_DEFAULTS.get(_model_name(model))
    if lowest is None:
        return None
    return "low" if lowest in ("none", "minimal") else lowest


class OpenAIJsonModel:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        reasoning_effort: str | None,
        max_output_tokens: int | None = None,
    ) -> None:
        self._client = client
        self.model = model
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._reasoning_taken: bool | None = None
        self._reasoning_check = asyncio.Lock()

    @classmethod
    def openai(
        cls,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        timeout_s: float,
        reasoning_effort: str | None = None,
        retries: int = RETRIES,
        max_output_tokens: int | None = None,
    ) -> OpenAIJsonModel:
        client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=retries
        )
        return cls(client, model, reasoning_effort, max_output_tokens)

    async def _reasoning(self) -> dict[str, dict[str, str]]:
        """The reasoning effort to send, when the model takes it. Asked on the first call, and on
        each later call until a check gets an answer."""
        effort = self._reasoning_effort
        if effort is None:
            return {}
        async with self._reasoning_check:
            if self._reasoning_taken is None:
                self._reasoning_taken = await takes_reasoning_effort(
                    self._client, self.model, effort
                )
        return {"reasoning": {"effort": effort}} if self._reasoning_taken else {}

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> ModelAnswer:
        try:
            response = await self._client.responses.create(
                model=self.model,
                instructions=system,
                input=user,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": name,
                        "schema": schema,
                        "strict": True,
                    }
                },
                store=False,
                extra_body=await self._reasoning(),
                max_output_tokens=(
                    omit if self._max_output_tokens is None else self._max_output_tokens
                ),
            )
        except openai.OpenAIError as error:
            raise ModelCallError(
                f"the model call failed: {failure(error)}", temporary=temporary(error)
            ) from error
        if refusal := refused(response):
            raise ModelCallError(f"the model refused: {refusal}", temporary=False)
        if response.status != "completed":
            details = response.incomplete_details
            reason = details.reason if details and details.reason else response.status
            raise ModelCallError(f"the model's answer was cut short ({reason})", temporary=False)
        if response.usage:
            log.info(
                "model %s answered %s: %d tokens in, %d out",
                self.model,
                name,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
        try:
            answer = json.loads(response.output_text)
        except json.JSONDecodeError as error:
            raise ModelCallError(
                f"the model's answer is not JSON: {error}", temporary=False
            ) from error
        if not isinstance(answer, dict):
            raise ModelCallError("the model's answer is not a JSON object", temporary=False)
        usage = response.usage
        return ModelAnswer(
            data=answer,
            model=response.model,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
        )

    async def close(self) -> None:
        await self._client.close()


def refused(response: Response) -> str | None:
    """The model's refusal, when it refused instead of answering."""
    for item in response.output:
        if item.type == "message":
            for part in item.content:
                if part.type == "refusal":
                    return part.refusal
    return None


async def takes_reasoning_effort(client: AsyncOpenAI, model: str, effort: str) -> bool | None:
    """Whether the model takes this reasoning effort. A model without reasoning, such as
    gpt-4.1, refuses the parameter with a 400, as does a reasoning model asked for a level it
    lacks. None when the check fails another way, such as a timeout or an outage: the answer is
    still open."""
    try:
        await client.with_options(timeout=CHECK_TIMEOUT_S, max_retries=0).responses.create(
            model=model, input="Say ok.", store=False, extra_body={"reasoning": {"effort": effort}}
        )
    except openai.BadRequestError as error:
        log.info("model %s does not take reasoning effort %s: %s", model, effort, failure(error))
        return False
    except openai.OpenAIError as error:
        log.warning("could not check reasoning effort %s on %s: %s", effort, model, failure(error))
        return None
    log.info("model %s takes reasoning effort %s", model, effort)
    return True


def temporary(error: openai.OpenAIError) -> bool:
    """A failure that trying again later can cure: no answer in time, no connection, a rate
    limit or a server error. A rejected request, such as an unknown model, is not."""
    if isinstance(error, openai.APITimeoutError | openai.APIConnectionError):
        return True
    if isinstance(error, openai.APIStatusError):
        return error.status_code == 429 or error.status_code >= 500
    return False


def failure(error: openai.OpenAIError) -> str:
    """What went wrong, without the provider's response body, which can echo key material."""
    if isinstance(error, openai.APITimeoutError):
        return "timed out"
    if isinstance(error, openai.APIConnectionError):
        return "could not reach the model service"
    if isinstance(error, openai.APIStatusError):
        body = error.body if isinstance(error.body, dict) else {}
        code = body.get("code") or body.get("type") or ""
        return f"HTTP {error.status_code} {code}".strip()
    return type(error).__name__
