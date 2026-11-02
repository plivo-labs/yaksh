"""The reader of Pipecat traces (1.14). One reply is one turn span. Pipecat has no span at the
end of the caller's speech, so it is the speech start less the agent's total; the speech start
is the first TTS audio, before Pipecat's output transport sends it. The LLM requests of a reply
start after that end: an earlier one in the same turn answered a part of the caller's speech,
and Pipecat cancelled it when the caller spoke again."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise

from yaksh.evaluation.trace_maps.reading import (
    AgentReply,
    Framework,
    Reading,
    TraceSpan,
    covered_ns,
    ms,
    seconds,
    with_remainder,
)

CORE = (
    "end_of_turn",
    "llm_inference",
    "function_handler",
    "sentence_aggregation",
    "speech_synthesis",
    "pipeline",
)


def read(spans: Sequence[TraceSpan]) -> Reading | None:
    turns = sorted((span for span in spans if span.name == "turn"), key=lambda span: span.start_ns)
    if not turns:
        return None
    children: Mapping[str | None, list[TraceSpan]] = defaultdict(list)
    for span in sorted(spans, key=lambda span: span.start_ns):
        children[span.parent_span_id].append(span)
    anchors, replies = [], []
    for turn in turns:
        tts = [child for child in children.get(turn.span_id, []) if child.name == "tts"]
        if not tts:
            continue
        ttfb = seconds(tts[0], "metrics.ttfb")
        speech_ns = tts[0].start_ns + (ttfb or 0)
        anchors.append(speech_ns)
        reply = turn_reply(turn, children.get(turn.span_id, []), speech_ns, ttfb)
        if reply is not None:
            replies.append(reply)
    return Reading(framework=Framework.PIPECAT, core=CORE, anchors_ns=anchors, replies=replies)


def turn_reply(
    turn: TraceSpan,
    spans: Sequence[TraceSpan],
    speech_ns: int,
    tts_ttfb: int | None,
) -> AgentReply | None:
    """The reply of one turn; None for a turn with no caller speech before it, as the
    greeting. It has no STT TTFS: with Deepgram, Pipecat's STT TTFB stops at the answer to the
    finalize request sent at the VAD stop, so it always holds stop_secs (decision 0036)."""
    total_ns = seconds(turn, "turn.user_bot_latency_seconds")
    if total_ns is None:
        return None
    total_ms = ms(total_ns)
    if tts_ttfb is None:
        return AgentReply(speech_ns, total_ms, incomplete="the first tts span has no TTFB")
    caller_end = speech_ns - total_ns
    first_tts = next(span for span in spans if span.name == "tts")
    llm = [
        span
        for span in spans
        if span.name == "llm" and caller_end <= span.start_ns < first_tts.start_ns
    ]
    if not llm or any(seconds(span, "metrics.ttfb") is None for span in llm):
        return AgentReply(speech_ns, total_ms, incomplete="an llm span or its TTFB is missing")
    first_tokens = [
        (span.start_ns, span.start_ns + (seconds(span, "metrics.ttfb") or 0)) for span in llm
    ]
    tools = [(earlier.end_ns, later.start_ns) for earlier, later in pairwise(llm)]
    parts = {
        "end_of_turn": covered_ns([(caller_end, llm[0].start_ns)], caller_end, speech_ns),
        "llm_inference": covered_ns(first_tokens, caller_end, speech_ns),
        "function_handler": covered_ns(tools, caller_end, speech_ns),
        "sentence_aggregation": covered_ns(
            [(first_tokens[-1][1], first_tts.start_ns)], caller_end, speech_ns
        ),
        "speech_synthesis": tts_ttfb,
    }
    with_rest, overlapping = with_remainder(total_ns, parts)
    return AgentReply(speech_ns, total_ms, with_rest, None, None, overlapping)
