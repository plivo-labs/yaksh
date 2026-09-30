"""Structured JSON answers from an OpenAI-compatible API, for generating test scenarios."""

import json
import logging
from typing import Any

import openai
from openai import AsyncOpenAI

from truman.domain.errors import UnavailableError

log = logging.getLogger(__name__)

TIMEOUT_S = 90.0
RETRIES = 1
"""One retry: someone is waiting for the answer in the console."""


class OpenAIJsonModel:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self.model = model

    @classmethod
    def openai(cls, api_key: str, model: str, *, base_url: str | None = None) -> OpenAIJsonModel:
        client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=TIMEOUT_S, max_retries=RETRIES
        )
        return cls(client, model)

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
