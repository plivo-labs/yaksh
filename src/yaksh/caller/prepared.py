"""Speech that the caller makes before the call starts, so that it plays at once: the persona's own
voicemail greeting, or the scenario's interruption lines."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from yaksh.diagnostics import describe_exception
from yaksh.domain.conversations import CallRequest
from yaksh.integrations.speech.audio import speak_once
from yaksh.integrations.speech.tts import tts_service

log = logging.getLogger(__name__)

Speak = Callable[[str], Awaitable[bytes]]


class Prepared:
    """The call's speech made before it starts, each item a future of 8 kHz PCM. A call has an
    own greeting or lines, never both: its voicemail answers only when the persona does not. A
    call in a process of its own makes the same items from its request, and the worker fills
    them there by their place in `items`."""

    def __init__(self, request: CallRequest) -> None:
        plan = request.answering
        own = plan.voicemail.own_greeting if plan and plan.voicemail else None
        self._texts = [*([own] if own is not None else []), *(i.say for i in request.interruptions)]
        loop = asyncio.get_running_loop()
        self.items: tuple[asyncio.Future[bytes], ...] = tuple(
            loop.create_future() for _ in self._texts
        )
        """In the order they are made; the link names each one by its place here."""
        self.own = self.items[0] if own is not None else None
        """The persona's own voicemail greeting; None when the call plays none."""
        self.lines = self.items[1:] if own is not None else self.items
        """Each interruption line, in the scenario's order."""
        self._conversation_id = request.conversation_id
        self._making: asyncio.Future[None] | None = None

    def make(self, speak: Speak) -> None:
        """Start making the items in order, one request at a time, so that a burst of call
        starts adds one speech request for each call, not one for each line."""
        if self._texts:
            self._making = asyncio.ensure_future(self._make_all(speak))

    def fill(self, index: int, made: bytes | BaseException) -> None:
        """Set an item; one that the call gave up on stays as it is."""
        item = self.items[index]
        if item.done():
            return
        if isinstance(made, BaseException):
            item.set_exception(made)
        else:
            item.set_result(made)

    async def close(self) -> None:
        """Stop making speech that the call no longer needs. A failure that nothing read is
        read here, so it is not logged as lost."""
        if self._making is not None:
            self._making.cancel()
            await asyncio.gather(self._making, return_exceptions=True)
        for item in self.items:
            if item.done() and not item.cancelled():
                item.exception()
            item.cancel()

    async def _make_all(self, speak: Speak) -> None:
        for index, text in enumerate(self._texts):
            try:
                made: bytes | BaseException = await self._twice(speak, text)
            except Exception as error:
                made = error
            self.fill(index, made)

    async def _twice(self, speak: Speak, text: str) -> bytes:
        """The speech of the text; a failed request is tried once more."""
        try:
            return await speak(text)
        except Exception as error:
            log.warning(
                "conversation %s: speech before the call failed, trying once more: %s",
                self._conversation_id,
                describe_exception(error),
            )
            return await speak(text)


async def spoken(key: str, request: CallRequest, text: str) -> bytes:
    """The text in the persona's voice, through the same text-to-speech as its replies."""
    service = tts_service(
        request.app_settings, request.voice, request.caller_language, key, one_shot=True
    )
    return await speak_once(service, text)
