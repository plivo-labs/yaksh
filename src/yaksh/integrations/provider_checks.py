"""Short, real requests that show whether a provider accepts a key and the settings around it:
for Check and save before a key is stored, and for the Test buttons. Each one raises
ProviderCheckError with a reason that never holds the key."""

import asyncio
import json

import aiohttp
import openai
from openai import AsyncOpenAI
from pipecat.classifiers.base_classifier import ChoiceQuestion
from pipecat.classifiers.typesafe.jev.classifier import JevClassifier

from yaksh.diagnostics import describe_exception
from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.voices import VoiceProvider, VoiceSettings
from yaksh.integrations.elevenlabs import ElevenLabsClient
from yaksh.integrations.openai_models import failure, takes_reasoning_effort
from yaksh.integrations.plivo import PlivoApi, PlivoError

TIMEOUT_S = 20.0
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
SILENCE_8K = bytes(8000)
"""Half a second of 16-bit silence at 8 kHz: Deepgram transcribes it to nothing."""


class ProviderCheckError(Exception):
    pass


def llm_client(base_url: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT_S, max_retries=0)


async def llm_models(base_url: str, api_key: str) -> list[str]:
    """The model ids the provider lists; this also proves the key and the base URL."""
    client = llm_client(base_url, api_key)
    try:
        return sorted({model.id async for model in client.models.list()})
    except openai.OpenAIError as error:
        raise ProviderCheckError(f"the LLM provider refused the key: {failure(error)}") from None
    finally:
        await client.close()


async def check_llm(base_url: str, api_key: str, model: str, effort: str | None) -> None:
    """One short answer from the model, with the reasoning effort the caller sends."""
    client = llm_client(base_url, api_key)
    extra = {} if effort is None else {"reasoning": {"effort": effort}}
    try:
        await client.responses.create(model=model, input="Say ok.", store=False, extra_body=extra)
    except openai.OpenAIError as error:
        raise ProviderCheckError(f"model {model}: {failure(error)}") from None
    finally:
        await client.close()


async def reasoning_efforts(base_url: str, api_key: str, model: str) -> list[str]:
    """The reasoning efforts the model takes; empty for a model without reasoning. A plain
    request goes first, so a model the provider cannot serve, such as an Azure model with no
    deployment, fails with the provider's reason instead of as an effort the model refuses.
    Raises when any answer stays open, so a timeout never reads as a refusal."""
    await check_llm(base_url, api_key, model, None)
    client = llm_client(base_url, api_key)
    try:
        answers = await asyncio.gather(
            *(takes_reasoning_effort(client, model, effort) for effort in REASONING_EFFORTS)
        )
    finally:
        await client.close()
    if any(answer is None for answer in answers):
        raise ProviderCheckError(f"could not check the reasoning efforts of {model}; try again")
    return [effort for effort, takes in zip(REASONING_EFFORTS, answers, strict=True) if takes]


async def check_deepgram(base_url: str, api_key: str, model: str) -> None:
    """A transcription of a short silence with the model the caller uses."""
    url = f"{base_url.rstrip('/')}/v1/listen"
    params = {"model": model, "encoding": "linear16", "sample_rate": "8000", "channels": "1"}
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "audio/raw"}
    try:
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)) as session,
            session.post(url, params=params, headers=headers, data=SILENCE_8K) as response,
        ):
            status, body = response.status, await response.text()
    except (aiohttp.ClientError, TimeoutError) as error:
        raise ProviderCheckError(f"Deepgram did not answer: {describe_exception(error)}") from None
    if status >= 400:
        raise ProviderCheckError(f"Deepgram answered {status}{deepgram_reason(body)}")


def deepgram_reason(body: str) -> str:
    """Deepgram's error code and message, never the rest of the body, which can echo the
    request."""
    try:
        error = json.loads(body)
    except ValueError:
        return ""
    if not isinstance(error, dict):
        return ""
    parts = [str(error[key]) for key in ("err_code", "err_msg") if isinstance(error.get(key), str)]
    return f": {' '.join(parts)}" if parts else ""


async def check_elevenlabs(api_key: str, voice_id: str) -> None:
    """One short word of speech, so a key limited to speech passes."""
    voice = VoiceSettings(provider=VoiceProvider.ELEVENLABS, id=voice_id)
    try:
        spoken = await ElevenLabsClient(api_key).speak(voice, Language.EN, "OK")
    except UnavailableError as error:
        raise ProviderCheckError(str(error)) from None
    if spoken is None:
        raise ProviderCheckError(f"the ElevenLabs account cannot use voice {voice_id}")


async def check_typesafe(api_key: str, model: str) -> None:
    """One question to Jev."""
    classifier = JevClassifier(api_key=api_key, model=model)
    question = ChoiceQuestion(instructions="Is the sky blue?", options={"yes": "Yes", "no": "No"})
    try:
        await asyncio.wait_for(classifier.choice("The sky is blue.", {"q": question}), TIMEOUT_S)
    except Exception as error:
        raise ProviderCheckError(f"TypeSafe: {describe_exception(error)}") from None
    finally:
        await classifier.cleanup()


async def check_plivo(auth_id: str, auth_token: str) -> int:
    """How many numbers the account lists; this proves the Auth ID and Auth token."""
    try:
        return len(await PlivoApi(auth_id, auth_token).list_numbers())
    except PlivoError as error:
        raise ProviderCheckError(f"Plivo: {error}") from None
