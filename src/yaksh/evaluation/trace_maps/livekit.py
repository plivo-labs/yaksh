"""The reader of LiveKit Agents traces (1.8). A reply is the agent's first speech after the end of
the caller's speech in a user turn. Each part counts only between that end and the speech start.

The agent's total is lk.e2e_latency of the turn that speaks. A reply after a tool call in the same
agent has two turns or more, linked by lk.parent_generation_id. When the tool hands the call to a
new agent, the new agent's turn speaks with no lk.e2e_latency: then the total is the speech start
less the end of the caller's speech by the user turn, the same point that lk.e2e_latency counts
from.

LiveKit runs an end-of-turn check when the VAD reports the end of the caller's speech, and again
when a final transcript comes after it; lk.eou.source says which. The start of the VAD's check
divides the time before the turn detection into the VAD's wait and the wait for the transcript
past it. A turn with no VAD check takes the VAD wait of the trace's other turns: the VAD waits
the same silence each time. A trace with no VAD check, as with no turn detector, keeps the two
together."""

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence

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

CORE_JOINED = (
    "vad_and_stt",
    "turn_detection",
    "llm_inference",
    "function_handler",
    "speech_synthesis",
    "pipeline",
)
CORE_SPLIT = ("endpointing_wait", "transcription", *CORE_JOINED[1:])
NAMES = frozenset({"agent_session", "user_turn", "agent_turn", "agent_speaking"})
SAME_END_NS = 100_000_000
"""How near the end of the caller's speech by lk.e2e_latency must be to the one by the user
turn: the same point, so a larger gap means that the speech answers another user turn."""

type Children = Mapping[str | None, list[TraceSpan]]


def read(spans: Sequence[TraceSpan]) -> Reading | None:
    if not any(span.name in NAMES for span in spans):
        return None
    children: Children = defaultdict(list)
    for span in sorted(spans, key=lambda span: span.start_ns):
        children[span.parent_span_id].append(span)
    turns = sorted((span for span in spans if span.name == "agent_turn"), key=lambda s: s.start_ns)
    speeches = sorted(
        (
            (min(span.start_ns for span in speaking), turn)
            for turn in turns
            if (speaking := named(children, turn, "agent_speaking"))
        ),
        key=lambda speech: speech[0],
    )
    users = sorted(
        (
            span
            for span in spans
            if span.name == "user_turn" and seconds(span, "lk.end_of_turn_delay")
        ),
        key=lambda span: span.start_ns,
    )
    vad_waits = [end - caller_end_of(user) for user in users if (end := vad_end(user, children))]
    vad_ns = round(statistics.median(vad_waits)) if vad_waits else None
    replies = []
    for index, user in enumerate(users):
        caller_end = caller_end_of(user)
        following = users[index + 1].start_ns if index + 1 < len(users) else None
        answer = next(
            (
                (start, turn)
                for start, turn in speeches
                if start > caller_end and (following is None or start < following)
            ),
            None,
        )
        if answer is not None and (
            reply := user_reply(user, caller_end, *answer, turns, children, vad_ns)
        ):
            replies.append(reply)
    return Reading(
        framework=Framework.LIVEKIT,
        core=CORE_JOINED if vad_ns is None else CORE_SPLIT,
        anchors_ns=sorted(span.start_ns for span in spans if span.name == "agent_speaking"),
        replies=replies,
    )


def named(children: Children, span: TraceSpan, name: str) -> list[TraceSpan]:
    return [child for child in children.get(span.span_id, []) if child.name == name]


def checks(children: Children, user: TraceSpan) -> list[TraceSpan]:
    """The end-of-turn checks of the user turn: its children up to 1.8.9, the children of its
    eou_wait span from 1.8.10."""
    return named(children, user, "eou_detection") + [
        check
        for wait in named(children, user, "eou_wait")
        for check in named(children, wait, "eou_detection")
    ]


def caller_end_of(user: TraceSpan) -> int:
    return user.end_ns - (seconds(user, "lk.end_of_turn_delay") or 0)


def vad_end(user: TraceSpan, children: Children) -> int | None:
    """When the VAD reported the end of the caller's speech: the start of the last check of the
    user turn with lk.eou.source "vad" after that end. None when LiveKit ran none, as when no
    transcript was there yet at the VAD's end."""
    caller_end = caller_end_of(user)
    return max(
        (
            span.start_ns
            for span in checks(children, user)
            if span.attributes.get("lk.eou.source") == "vad" and span.start_ns >= caller_end
        ),
        default=None,
    )


def user_reply(
    user: TraceSpan,
    caller_end: int,
    speech_ns: int,
    speaking: TraceSpan,
    turns: Sequence[TraceSpan],
    children: Children,
    vad_ns: int | None,
) -> AgentReply | None:
    """The reply to the user turn; None when the speech is not one: its lk.e2e_latency counts
    from another user turn, or it has none and no tool of this user turn hands the call over
    before it, as an idle reminder or a handoff that an earlier user turn started."""
    e2e = seconds(speaking, "lk.e2e_latency")
    if e2e is not None:
        if abs(speech_ns - e2e - caller_end) > SAME_END_NS:
            return None
        total = e2e
        chain = generation_chain(speaking, turns)
    else:
        chain = [turn for turn in turns if turn.end_ns > user.end_ns and turn.start_ns < speech_ns]
        if len(chain) < 2 or chain[-1] is not speaking or chain[0].start_ns < user.start_ns:
            return None
        if not all(named(children, turn, "function_tool") for turn in chain[:-1]):
            return None
        total = speech_ns - caller_end
    total_ms = ms(total)
    stt_ns = seconds(user, "lk.transcription_delay")
    stt = None if stt_ns is None else ms(stt_ns)

    def incomplete(reason: str) -> AgentReply:
        return AgentReply(speech_ns, total_ms, stt_ttfs_ms=stt, incomplete=reason)

    if chain is None:
        return incomplete("an earlier turn of the reply is missing")
    turn_end = max(caller_end, user.end_ns)
    nodes = [node for turn in chain for node in named(children, turn, "llm_node")]
    if not all(named(children, turn, "llm_node") for turn in chain) or any(
        seconds(node, "lk.response.ttft") is None and node.end_ns > turn_end for node in nodes
    ):
        return incomplete("an llm_node or its TTFT is missing")
    if not all(named(children, turn, "function_tool") for turn in chain[:-1]):
        return incomplete("a function_tool is missing")
    tts = named(children, speaking, "tts_node")
    ttfb = seconds(tts[0], "lk.response.ttfb") if tts else None
    if ttfb is None:
        return incomplete("a tts_node or its TTFB is missing")
    eou = checks(children, user)
    if vad_ns is None:
        detected = max((span.start_ns for span in eou), default=user.end_ns)
        before_check = {"vad_and_stt": covered_ns([(caller_end, detected)], caller_end, speech_ns)}
    else:
        vad_stop = vad_end(user, children) or caller_end + vad_ns
        detected = max((span.start_ns for span in eou), default=min(vad_stop, user.end_ns))
        vad_stop = min(vad_stop, detected)
        before_check = {
            "endpointing_wait": covered_ns([(caller_end, vad_stop)], caller_end, speech_ns),
            "transcription": covered_ns([(vad_stop, detected)], caller_end, speech_ns),
        }
    llm_starts = sorted(node.start_ns for node in nodes)
    first_tokens = [
        (node.start_ns, node.start_ns + ttft)
        for node in nodes
        if (ttft := seconds(node, "lk.response.ttft")) is not None
    ]
    tools = [
        (
            tool.start_ns,
            next((start for start in llm_starts if start >= tool.start_ns), tool.end_ns),
        )
        for turn in chain[:-1]
        for tool in named(children, turn, "function_tool")
    ]
    parts = before_check | {
        "turn_detection": covered_ns([(detected, user.end_ns)], caller_end, speech_ns),
        "llm_inference": covered_ns(first_tokens, turn_end, speech_ns),
        "function_handler": covered_ns(tools, caller_end, speech_ns),
        "speech_synthesis": covered_ns(
            [(tts[0].start_ns, tts[0].start_ns + ttfb)], turn_end, speech_ns
        ),
    }
    with_rest, overlapping = with_remainder(total, parts)
    return AgentReply(speech_ns, total_ms, with_rest, stt, None, overlapping)


def generation_chain(speaking: TraceSpan, turns: Sequence[TraceSpan]) -> list[TraceSpan] | None:
    """The turns of a reply in one agent, first to the one that speaks, by
    lk.parent_generation_id; None when a turn that one names is not in the trace."""
    by_generation = {turn.attributes.get("lk.generation_id"): turn for turn in turns}
    chain = [speaking]
    while parent := chain[0].attributes.get("lk.parent_generation_id"):
        earlier = by_generation.get(parent)
        if earlier is None or earlier in chain:
            return None
        chain.insert(0, earlier)
    return chain
