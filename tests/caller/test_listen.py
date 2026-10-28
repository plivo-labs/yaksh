import asyncio
import base64
import uuid
from typing import Any

from yaksh.caller.listen import LiveAudio
from yaksh.db.session import notify_connection
from yaksh.domain.listen import AGENT, channels, encode


async def test_the_opening_audio_reaches_a_listener_who_asked_before_the_call_started(
    database_url: str,
) -> None:
    conversation_id = uuid.uuid4()
    audio_channel, _ = channels(conversation_id)
    heard: asyncio.Queue[str] = asyncio.Queue()

    def notified(*args: Any) -> None:
        heard.put_nowait(args[3])

    async with notify_connection(database_url) as listener:
        await listener.add_listener(audio_channel, notified)
        live = LiveAudio(database_url, conversation_id)
        live.put(AGENT, 0.0, b"\x01\x02")
        payload = await asyncio.wait_for(heard.get(), 5)
        await live.close()

    assert base64.b64decode(payload) == encode(AGENT, 0.0, b"\x01\x02")
