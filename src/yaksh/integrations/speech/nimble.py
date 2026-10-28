"""Nimble, Plivo's text-to-speech, over its live websocket: one socket per call, one context per
reply, the reply's text streamed in as it is generated, its audio and per-character timestamps
streamed back. Pipecat has no Nimble service, so this one follows Pipecat's Cartesia service.

The gateway's protocol: a context opens with its first text message, which carries the voice and
the options; later text messages append text; `finish` ends the text; `cancel` stops the reply
and keeps the socket. Audio comes as binary frames, a u16 little-endian length, the context id
and the audio. Events are JSON: `timestamps`, `warning`, `error` (ends the context, not billed)
and `done`."""

import base64
import itertools
import json
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from loguru import logger
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame, TTSStoppedFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import WebsocketTTSService
from websockets.protocol import State

from yaksh.diagnostics import describe_exception
from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import ProviderVoice, VoiceGender, VoiceProvider, VoiceSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.vendor import TtsVendor

LANGUAGES = VoiceProvider.NIMBLE.traits.languages
"""The languages Nimble pins; it speaks no other of Yaksh's."""
RETRYABLE = frozenset(
    {"auth_unavailable", "concurrency_limit", "at_capacity", "draining", "backend_error"}
)
"""Errors the gateway may not give again: a reply that has no audio yet is tried once more."""
TIMEOUT = aiohttp.ClientTimeout(total=10)


def websocket_of(base_url: str) -> str:
    """The gateway's websocket address: wss for https, ws for http."""
    scheme, rest = base_url.rstrip("/").split("://", 1)
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest}"


def basic_auth(credential: str) -> str:
    """`credential` is the Auth ID and Auth token as `id:token`, as Basic auth sends them."""
    return "Basic " + base64.b64encode(credential.encode()).decode()


@dataclass
class Reply:
    """One reply: its gateway context, the text sent so far, and its pending timestamp group."""

    text: str
    gateway_id: str = ""
    finished: bool = False
    has_audio: bool = False
    retried: bool = False
    group_start_ms: int | None = None
    group: list[str] = field(default_factory=list)


class NimbleTTSService(WebsocketTTSService):
    def __init__(
        self,
        *,
        credential: str,
        base_url: str,
        voice: str,
        language: Language,
        pace: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            push_text_frames=False,
            pause_frame_processing=False,
            sample_rate=SAMPLE_RATE,
            push_start_frame=True,
            settings=TTSSettings(model=None, voice=voice, language=None),
            **kwargs,
        )
        self._authorization = basic_auth(credential)
        self._url = websocket_of(base_url) + "/v1/synthesize/live"
        self._options = {
            "voice_id": voice,
            "language": language.value if language in LANGUAGES else "auto",
            "pace": pace,
            "timestamps": True,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 8000},
        }
        self._replies: dict[str, Reply] = {}
        """Each open reply by Pipecat's context id."""
        self._by_gateway: dict[str, str] = {}
        self._openings = itertools.count(1)
        self._receive_task = None

    def can_generate_metrics(self) -> bool:
        return True

    async def _connect(self) -> None:
        await super()._connect()
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self) -> None:
        await super()._disconnect()
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    async def _connect_websocket(self) -> None:
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return
            self._websocket = await self._websocket_connect(
                self._url, additional_headers={"Authorization": self._authorization}
            )
            await self._call_event_handler("on_connected")
        except Exception as error:
            await self.push_error(error_msg=f"Nimble refused the socket: {error}", exception=error)
            self._websocket = None
            await self._call_event_handler("on_connection_error", f"{error}")

    async def _disconnect_websocket(self) -> None:
        try:
            await self.stop_all_metrics()
            if self._websocket:
                await self._websocket.close()
        finally:
            self._websocket = None
            self._replies.clear()
            self._by_gateway.clear()
            await self._call_event_handler("on_disconnected")

    async def _reconnect_websocket(self, attempt_number: int) -> bool:
        """A socket lost during a reply loses the reply: the gateway does not resume it on a new
        socket, and replaying it would repeat words the agent heard. That ends the call, as any
        other Nimble failure does; a socket lost between replies is opened again."""
        if not self._replies:
            return await super()._reconnect_websocket(attempt_number)
        self._replies.clear()
        self._by_gateway.clear()
        await self._close_connection_contexts()
        await self.push_error(
            error_msg="Nimble's socket closed during a reply", force_treat_as_permanent=True
        )
        return False

    def _get_websocket(self) -> Any:
        if self._websocket:
            return self._websocket
        raise RuntimeError("the Nimble socket is not open")

    async def _send(self, message: dict[str, Any]) -> None:
        await self._get_websocket().send(json.dumps(message))

    async def _open(self, context_id: str, reply: Reply) -> None:
        """Open a gateway context for the reply with every piece of text it has so far. Each
        opening gets a new id: Pipecat can open a context again under the same id, and nothing
        the gateway still sends for an earlier opening may reach the new one."""
        self._by_gateway.pop(reply.gateway_id, None)
        reply.gateway_id = f"{context_id}-{next(self._openings)}"
        self._by_gateway[reply.gateway_id] = context_id
        await self._send(
            {
                "type": "text",
                "context_id": reply.gateway_id,
                "text": reply.text,
                "finish": reply.finished,
                **self._options,
            }
        )

    async def run_tts(self, text: str, context_id: str):
        if not self._websocket or self._websocket.state is State.CLOSED:
            await self._connect()
        reply = self._replies.get(context_id)
        if reply is not None and reply.text and not reply.text[-1].isspace() and text[:1] != " ":
            text = " " + text
        try:
            if reply is None:
                reply = self._replies[context_id] = Reply(text=text)
                await self._open(context_id, reply)
            else:
                reply.text += text
                await self._send({"type": "text", "context_id": reply.gateway_id, "text": text})
            await self.start_tts_usage_metrics(text)
        except Exception as error:
            yield ErrorFrame(error=f"Nimble did not take the text: {describe_exception(error)}")
            yield TTSStoppedFrame(context_id=context_id)
            return
        yield None

    async def flush_audio(self, context_id: str | None = None) -> None:
        """The reply's text is complete."""
        context_id = context_id or self.get_active_audio_context_id()
        reply = self._replies.get(context_id or "")
        if reply is None or reply.finished or not self._websocket:
            return
        reply.finished = True
        await self._send(
            {"type": "text", "context_id": reply.gateway_id, "text": "", "finish": True}
        )

    async def on_audio_context_interrupted(self, context_id: str) -> None:
        """Barge-in: the gateway stops the reply and keeps the socket."""
        await self.stop_all_metrics()
        await self._stop_reply(context_id)
        await super().on_audio_context_interrupted(context_id)

    async def on_audio_context_completed(self, context_id: str) -> None:
        """A reply's context ends after its `done`, or after its audio stopped for Pipecat's
        quiet time; the gateway stops a reply that never sent `done`."""
        await self._stop_reply(context_id)

    async def _stop_reply(self, context_id: str) -> None:
        """Audio still on its way for the reply is dropped by its context id."""
        reply = self._forget(context_id)
        if reply is not None and self._websocket:
            await self._send({"type": "cancel", "context_id": reply.gateway_id})

    def _forget(self, context_id: str) -> Reply | None:
        reply = self._replies.pop(context_id, None)
        if reply is not None:
            self._by_gateway.pop(reply.gateway_id, None)
        return reply

    async def _receive_messages(self) -> None:
        async for message in self._get_websocket():
            if isinstance(message, bytes):
                await self._audio(message)
            else:
                await self._event(json.loads(message))

    async def _audio(self, frame: bytes) -> None:
        length = int.from_bytes(frame[:2], "little")
        context_id = self._by_gateway.get(frame[2 : 2 + length].decode())
        reply = self._replies.get(context_id or "")
        if context_id is None or reply is None or not self.audio_context_available(context_id):
            return
        await self.stop_ttfb_metrics()
        reply.has_audio = True
        await self.append_to_audio_context(
            context_id,
            TTSAudioRawFrame(frame[2 + length :], SAMPLE_RATE, 1, context_id=context_id),
        )

    async def _event(self, event: dict[str, Any]) -> None:
        context_id = self._by_gateway.get(event.get("context_id", ""))
        reply = self._replies.get(context_id or "")
        if context_id is None or reply is None or not self.audio_context_available(context_id):
            if event.get("type") == "error" and "context_id" not in event:
                logger.warning(f"{self}: {event.get('code')}: {event.get('message')}")
            return
        match event.get("type"):
            case "timestamps":
                await self._timestamps(context_id, reply, event)
            case "done":
                await self._close_group(context_id, reply)
                await self.append_to_audio_context(
                    context_id, TTSStoppedFrame(context_id=context_id)
                )
                await self._end(context_id)
            case "error":
                await self._error(context_id, reply, event)
            case "warning":
                logger.warning(f"{self}: {event.get('code')}: {event.get('message')}")

    async def _timestamps(self, context_id: str, reply: Reply, event: dict[str, Any]) -> None:
        """Characters come grouped about a word, each group with one start: one word each."""
        for char, start_ms in zip(event["chars"], event["start_ms"], strict=True):
            if reply.group_start_ms is not None and start_ms != reply.group_start_ms:
                await self._close_group(context_id, reply)
            if reply.group_start_ms is None:
                reply.group_start_ms = start_ms
            reply.group.append(char)

    async def _close_group(self, context_id: str, reply: Reply) -> None:
        word = "".join(reply.group).strip()
        if word and reply.group_start_ms is not None:
            await self.add_word_timestamps([(word, reply.group_start_ms / 1000)], context_id)
        reply.group_start_ms = None
        reply.group = []

    async def _error(self, context_id: str, reply: Reply, event: dict[str, Any]) -> None:
        """A reply with no audio yet is tried once more in a new context on a retryable error;
        any other error ends the call, as replaying a reply the agent heard part of would
        repeat it."""
        code = event.get("code")
        if code in RETRYABLE and not reply.has_audio and not reply.retried:
            reply.retried = True
            await self._open(context_id, reply)
            return
        await self._end(context_id)
        await self.push_error(
            error_msg=f"Nimble refused the reply: {code}: {event.get('message')}",
            force_treat_as_permanent=True,
        )

    async def _end(self, context_id: str) -> None:
        self._forget(context_id)
        await self.remove_audio_context(context_id)


def tts(
    settings: AppSettings, voice: VoiceSettings, language: Language, key: str, *, one_shot: bool
) -> NimbleTTSService:
    """A one-shot service does not reconnect: a dropped socket fails the speech instead of
    ending it short as finished."""
    return NimbleTTSService(
        credential=key,
        base_url=settings.nimble.base_url,
        voice=voice.id,
        language=language,
        pace=voice.speed,
        stop_frame_timeout_s=quiet_s(one_shot),
        reconnect_on_error=not one_shot,
    )


async def voices(settings: AppSettings, key: str) -> list[ProviderVoice]:
    """The voices the account can use; this also proves the Auth ID, the token and that this
    server's IP is allowed."""
    url = f"{settings.nimble.base_url.rstrip('/')}/v1/voices"
    try:
        async with (
            aiohttp.ClientSession(timeout=TIMEOUT) as session,
            session.get(url, headers={"Authorization": basic_auth(key)}) as response,
        ):
            status, body = response.status, await response.text()
    except (aiohttp.ClientError, TimeoutError) as error:
        raise UnavailableError(f"Nimble did not answer: {describe_exception(error)}") from None
    if status == 401:
        raise UnavailableError(
            "Nimble refused the Auth ID and token (401); check them, and this server's IP on the "
            "account's IP allow list"
        )
    if status >= 400:
        raise UnavailableError(f"Nimble answered {status}")
    try:
        listed = json.loads(body)["voices"]
    except ValueError, KeyError, TypeError:
        raise UnavailableError("Nimble sent a voice list that is not JSON") from None
    return [provider_voice(entry) for entry in listed]


def provider_voice(entry: dict[str, Any]) -> ProviderVoice:
    gender = entry.get("gender")
    return ProviderVoice(
        id=entry["voice_id"],
        name=entry.get("name") or entry["voice_id"],
        gender=VoiceGender(gender) if gender in {"male", "female"} else None,
        accent=entry.get("accent_type"),
        listed_languages=tuple(
            Language(code) for code in entry.get("languages", []) if code in LANGUAGES
        ),
    )


async def lookup(settings: AppSettings, key: str, voice_id: str) -> ProviderVoice | None:
    return next((voice for voice in await voices(settings, key) if voice.id == voice_id), None)


async def check_voice(settings: AppSettings, key: str) -> str:
    """The first voice the account lists: the roster differs between gateways."""
    listed = await voices(settings, key)
    if not listed:
        raise UnavailableError("the Nimble account lists no voices")
    return listed[0].id


TTS = TtsVendor(service=tts, check_voice=check_voice, lookup=lookup)
