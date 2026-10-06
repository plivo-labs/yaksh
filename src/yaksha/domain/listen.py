"""A running call's audio on its way to a listener. Each message holds one piece of one side:
the side, where the piece starts on the pipeline's clock, and the audio as 8 kHz PCM16 mono, the
pipeline's rate for every transport."""

import struct
import uuid

AGENT = 0
CALLER = 1
HEADER = struct.Struct("<Bd")
LENGTH = struct.Struct("<I")
KEEPALIVE_S = 5.0
"""How often a listener asks the worker for the call's audio."""
WANT_S = 2 * KEEPALIVE_S
"""How long the worker keeps a call's audio after the last request: two requests."""


def encode(side: int, at_ms: float, pcm: bytes) -> bytes:
    return HEADER.pack(side, at_ms) + pcm


def framed(message: bytes) -> bytes:
    """A message with its length in front, for a byte stream."""
    return LENGTH.pack(len(message)) + message


def channels(conversation_id: uuid.UUID) -> tuple[str, str]:
    """The Postgres NOTIFY channels of a call: its audio, and the listeners' requests for it."""
    return f"listen_{conversation_id.hex}", f"want_{conversation_id.hex}"
