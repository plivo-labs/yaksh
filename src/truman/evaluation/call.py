"""What the evaluator reads from one saved conversation, and the metrics it computes."""

import asyncio
from pathlib import Path

from truman.db.models import Conversation
from truman.domain.conversations import CallerSettings, CallerUsage, LineFacts, Transcript
from truman.domain.evaluations import Metric, MetricKey
from truman.domain.latency import Latency, Span, waits
from truman.evaluation import metrics, speech


async def evaluate(conversation: Conversation, agent_speaks_first: bool) -> dict[MetricKey, Metric]:
    """The metrics of a saved call. A call that never connected has only its usage. One that
    failed before it was saved in full, or has no recording or caller replies, has no speech
    metrics: a missing value, never a zero. agent_speaks_first is the pinned agent's setting:
    without it, Truman's caller opens the call."""
    transcript = Transcript.model_validate(conversation.transcript or {})
    found = {
        MetricKey.USAGE: metrics.usage(
            transcript,
            parsed(CallerSettings, conversation.caller_settings),
            parsed(CallerUsage, conversation.caller_usage),
            parsed(LineFacts, conversation.line_facts),
        )
    }
    if not transcript.connected:
        return found
    found[MetricKey.AGENT_REPETITION] = metrics.agent_repetition(transcript.turns)
    opened = transcript.stream_opened_ms
    if opened is None:
        found[MetricKey.CAPTURE_FAULTS] = metrics.incomplete_record()
        return found
    gaps = media_gaps(transcript, opened)
    found[MetricKey.CAPTURE_FAULTS] = metrics.capture_faults(
        transcript, conversation.recording_path is not None, gaps
    )
    heard = await hear(conversation, transcript)
    if heard is None:
        return found
    goodbye = metrics.goodbye_from(transcript)
    paired = waits(
        opened,
        heard.replies,
        heard.speech.agent,
        heard.end_ms,
        goodbye_from_ms=goodbye,
        gaps=gaps,
        agent_opens=agent_speaks_first,
    )
    found[MetricKey.SPEECH] = Metric(value=heard.speech.model_dump(mode="json"))
    found[MetricKey.RESPONSE_TIME] = Metric(value=Latency.answered(paired).model_dump(mode="json"))
    found[MetricKey.TURN_TAKING] = metrics.turn_taking(paired)
    found[MetricKey.SPEAKING] = metrics.speaking(heard.speech, goodbye)
    return found


def media_gaps(transcript: Transcript, stream_opened_ms: int | None) -> list[Span]:
    """Where no media came from the agent's side, from the stream's opening on."""
    media = transcript.agent_media
    if media is None:
        return []
    if stream_opened_ms is None or media.first_ms <= stream_opened_ms:
        return media.gaps
    return [Span(start_ms=stream_opened_ms, end_ms=media.first_ms), *media.gaps]


def parsed[T: (CallerSettings, CallerUsage, LineFacts)](
    model: type[T], stored: dict[str, object] | None
) -> T | None:
    return None if stored is None else model.model_validate(stored)


async def hear(conversation: Conversation, transcript: Transcript) -> speech.Heard | None:
    """Both sides' speech; None for a call without a recording or its caller replies."""
    if (
        conversation.recording_path is None
        or transcript.recording_start_ms is None
        or transcript.caller_replies is None
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
        agent, voice, rate, transcript.recording_start_ms, transcript.caller_replies
    )
