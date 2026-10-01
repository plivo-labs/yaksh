"""Structured JSON answers from the Responses API of OpenAI or a compatible service, for
generating test scenarios."""

import asyncio
import json
import logging
from typing import Any

import openai
from openai import AsyncOpenAI
from openai.types.responses import Response

from truman.domain.errors import UnavailableError

log = logging.getLogger(__name__)

RETRIES = 1
"""One retry: someone is waiting for the answer in the console."""
CHECK_TIMEOUT_S = 15.0
"""For one try of the reasoning check, which takes about a second even at the highest effort."""


class OpenAIJsonModel:
    def __init__(self, client: AsyncOpenAI, model: str, reasoning_effort: str | None) -> None:
        self._client = client
        self.model = model
        self._reasoning_effort = reasoning_effort
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
    ) -> OpenAIJsonModel:
        client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=RETRIES
        )
        return cls(client, model, reasoning_effort)

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
    ) -> dict[str, Any]:
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
            )
        except openai.OpenAIError as error:
            raise UnavailableError(f"the model call failed: {failure(error)}") from error
        if refusal := refused(response):
            raise UnavailableError(f"the model refused: {refusal}")
        if response.status != "completed":
            details = response.incomplete_details
            reason = details.reason if details and details.reason else response.status
            raise UnavailableError(f"the model's answer was cut short ({reason})")
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
            raise UnavailableError(f"the model's answer is not JSON: {error}") from error
        if not isinstance(answer, dict):
            raise UnavailableError("the model's answer is not a JSON object")
        return answer

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
