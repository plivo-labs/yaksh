"""What the evaluator reads from one saved conversation, and the metrics it computes."""

import asyncio
from pathlib import Path

from truman.db.models import Conversation
from truman.domain.conversations import Transcript
from truman.domain.evaluations import Metric, MetricKey
from truman.evaluation import speech


async def evaluate(conversation: Conversation) -> dict[MetricKey, Metric]:
    transcript = Transcript.model_validate(conversation.transcript or {})
    metrics: dict[MetricKey, Metric] = {}
    measured = await measure(conversation, transcript)
    if measured is not None:
        heard, latency = measured
        metrics[MetricKey.SPEECH] = Metric(value=heard.model_dump(mode="json"))
        metrics[MetricKey.RESPONSE_TIME] = Metric(value=latency.model_dump(mode="json"))
    return metrics


async def measure(
    conversation: Conversation, transcript: Transcript
) -> tuple[speech.Speech, speech.Latency] | None:
    """Both sides' speech and the response times; None for a call without a recording."""
    if (
        conversation.recording_path is None
        or transcript.recording_start_ms is None
        or transcript.stream_opened_ms is None
    ):
        return None
    agent, rate = await asyncio.to_thread(speech.read_mono, Path(conversation.recording_path))
    voice = b""
    if conversation.caller_voice_path is not None:
        voice, voice_rate = await asyncio.to_thread(
            speech.read_mono, Path(conversation.caller_voice_path)
        )
        if voice_rate != rate:
            raise ValueError(f"the caller voice is at {voice_rate} Hz, the recording at {rate} Hz")
    return await speech.measure(
        agent,
        voice,
        rate,
        transcript.recording_start_ms,
        transcript.stream_opened_ms,
        transcript.caller_replies or [],
    )
