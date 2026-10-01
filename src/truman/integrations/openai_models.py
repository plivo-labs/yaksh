"""Structured JSON answers from an OpenAI-compatible API, for generating test scenarios."""

import asyncio
import json
import logging
from typing import Any

import openai
from openai import AsyncOpenAI

from truman.domain.errors import UnavailableError

log = logging.getLogger(__name__)

RETRIES = 1
"""One retry: someone is waiting for the answer in the console."""
CHECK_TIMEOUT_S = 60.0


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

    async def _reasoning(self) -> dict[str, str]:
        """The reasoning effort to send, when the model takes it; asked on the first call."""
        effort = self._reasoning_effort
        if effort is None:
            return {}
        async with self._reasoning_check:
            if self._reasoning_taken is None:
                self._reasoning_taken = await takes_reasoning_effort(
                    self._client, self.model, effort
                )
        return {"reasoning_effort": effort} if self._reasoning_taken else {}

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": schema, "strict": True},
                },
                extra_body=await self._reasoning(),
            )
        except openai.OpenAIError as error:
            raise UnavailableError(f"the model call failed: {failure(error)}") from error
        choice = response.choices[0]
        if choice.message.refusal:
            raise UnavailableError(f"the model refused: {choice.message.refusal}")
        if choice.finish_reason != "stop":
            raise UnavailableError(f"the model's answer was cut short ({choice.finish_reason})")
        if response.usage:
            log.info(
                "model %s answered %s: %d tokens in, %d out",
                self.model,
                name,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )
        try:
            answer = json.loads(choice.message.content or "")
        except json.JSONDecodeError as error:
            raise UnavailableError(f"the model's answer is not JSON: {error}") from error
        if not isinstance(answer, dict):
            raise UnavailableError("the model's answer is not a JSON object")
        return answer

    async def close(self) -> None:
        await self._client.close()


async def takes_reasoning_effort(client: AsyncOpenAI, model: str, effort: str) -> bool:
    """Whether the model takes `reasoning_effort` at this level. A model without reasoning,
    such as gpt-4.1, refuses the parameter. A refusal or any other failure counts as no, so the
    model then runs at its own default."""
    try:
        await client.with_options(timeout=CHECK_TIMEOUT_S).chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say ok."}],
            extra_body={"reasoning_effort": effort},
        )
    except openai.BadRequestError:
        taken = False
    except openai.OpenAIError as error:
        log.warning("could not check reasoning effort %s on %s: %s", effort, model, failure(error))
        taken = False
    else:
        taken = True
    log.info(
        "model %s %s reasoning effort %s", model, "takes" if taken else "does not take", effort
    )
    return taken


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
