"""The evidence view: the one text every LLM judge and the review screen read about a call. It
leaves out what must not sway a judge: the caller's own reason for ending the call, the noise
setting, the agent's configuration and its documents. A change to the text is a new version."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from yaksh.domain.agent_records import (
    AgentRecord,
    RecordMove,
    RecordTool,
    RecordTurn,
    StoredRecord,
)
from yaksh.domain.agents import Direction, Transport
from yaksh.domain.answering import (
    SCREENER_LABELS,
    VOICEMAIL_LABELS,
    AnsweredBy,
    Answering,
    MachineLine,
    Voicemail,
)
from yaksh.domain.conversations import (
    EndReason,
    Provenance,
    Role,
    ToolItem,
    Turn,
    WireEvent,
    WireEventKind,
    picked_up,
    voicemail_answered,
)
from yaksh.domain.record_sources import RECORD_PROVIDERS
from yaksh.domain.scenarios import Fact
from yaksh.domain.stops import (
    SOONEST_STOP_MS,
    STOP_WINDOW_MS,
    LineStop,
    StopReason,
    StopResult,
)

EVIDENCE_VIEW_VERSION = 11
NO_TIME = datetime.min.replace(tzinfo=UTC)

TRANSCRIPTION_NOTE = {
    Transport.PHONE: (
        "The agent's lines are Yaksh's speech-to-text of the agent's audio. Judge what was said, "
        'not the spelling: "for" can mean "four", and "to" can mean "two".'
    ),
    Transport.TEXT: (
        "This test ran over text, with no phone call: the agent's lines are the exact text it "
        "sent. The agent ran its voice rules, so spelled and spoken-form read-backs are "
        'expected. A "Tool call" line under an agent line is a tool that the agent called in '
        "that turn, with its arguments and output, as the agent reported them."
    ),
}

ENDED_BY = {
    EndReason.AGENT_HANGUP: "The agent hung up",
    EndReason.CALLER_HANGUP: "Yaksh's caller hung up",
    EndReason.TURN_LIMIT: "Yaksh's caller hung up at the test's turn limit",
    EndReason.DURATION_LIMIT: "Yaksh ended the call at the test's time limit",
    EndReason.VOICEMAIL_ENDED: "The voicemail of Yaksh's caller stopped recording and hung up",
    EndReason.SCREENER_ENDED: "The call screener of Yaksh's caller hung up",
}
RECORDED = {
    MachineLine.GREETING: "Voicemail",
    MachineLine.MAILBOX_FULL: "Voicemail",
    MachineLine.SCREENER: "Call screener",
    MachineLine.REPLY: "Call screener",
}
MACHINE_NOTE = (
    "A line marked recorded is played by the phone of Yaksh's caller, its voicemail or its call "
    "screener: a fixed recording that cannot hear or answer the agent."
)


@dataclass(frozen=True)
class CallView:
    brief: str
    agent_data: list[Fact]
    instructions: str
    known_facts: list[Fact]
    unknown_facts: list[str]
    today: date
    time_zone: str
    direction: Direction
    transport: Transport
    agent_number: str | None
    """The number Yaksh called; inbound agents only."""
    yaksh_number: str | None
    agent_caller_id: str | None
    """The number an outbound agent called from."""
    hangup_source: str | None
    end_reason: EndReason | None
    talk_ms: int | None
    turns: list[Turn]
    answered_by: AnsweredBy = AnsweredBy.CALLER
    answering: Answering | None = None
    """The voicemail and call screener of Yaksh's caller, when one of them answered."""
    events: list[WireEvent] = field(default_factory=list)
    record: StoredRecord | None = None
    """The agent's own record of the call; None when the agent has no record source or the
    test ran over text."""
    stops: Mapping[int, LineStop] = field(default_factory=dict)
    """When the agent's speech stopped after each interruption line, by the line's number."""


def render(view: CallView) -> str:
    """The view without its item: what one request about every item of a call can share."""
    sections = [
        "\n".join(
            [
                "AGENT",
                f"Brief: {view.brief}",
                f"Agent data sent with this call: {facts(view.agent_data)}.",
            ]
        ),
        "\n".join(
            [
                "CALLER",
                f"Instructions: {view.instructions}",
                f"Known facts: {facts(view.known_facts)}.",
                f"Facts the caller does not know: {', '.join(view.unknown_facts) or 'none'}.",
                *fixed_lines(view.turns),
            ]
        ),
        "\n".join(
            [
                "DATE",
                f"Today is {view.today:%A}, {view.today.day} {view.today:%B %Y}. "
                f"Time zone: {view.time_zone}.",
            ]
        ),
        "\n".join(["CALL FACTS", who_called(view), *answered(view), how_it_ended(view)]),
        "\n".join(
            [
                "TRANSCRIPT",
                TRANSCRIPTION_NOTE[view.transport],
                *([MACHINE_NOTE] if view.answered_by is not AnsweredBy.CALLER else []),
                *transcript(view.turns, view.events, view.stops),
            ]
        ),
    ]
    if view.record is not None:
        sections.append("\n".join(agent_record(view.record)))
    return "\n\n".join(sections)


def record_lines(record: AgentRecord) -> list[str]:
    """The record's lines a judge can quote, numbered from 1 in the view: the call in the
    agent's own words, with its tool calls and its moves in their place, then the values it
    saved. The caller's lines are kept only when they are what the agent heard during the
    call."""
    heard = RECORD_PROVIDERS[record.provider].live_transcript
    spoken = [turn for turn in record.turns if heard or turn.role is Role.AGENT]
    first = record.moves[0] if record.moves else None
    serving = None
    lines = []
    for line in in_order(spoken, record.tools, record.moves):
        if isinstance(line, RecordTurn):
            if serving is not None and line.node != serving.node:
                lines.append(f"The next line is from {node_name(line.node)}")
            lines.append(record_turn_line(line))
        elif isinstance(line, RecordMove):
            serving = line
            lines.append(move_line(line, first))
        else:
            lines.append(record_tool_line(line, serving))
    return lines + [f"Saved: {value.name} = {value.value}" for value in record.saved]


type RecordEvent = RecordTool | RecordMove
type RecordLine = RecordTurn | RecordEvent


def in_order(
    turns: list[RecordTurn], tools: list[RecordTool], moves: list[RecordMove]
) -> list[RecordLine]:
    """The turns in the record's order, each tool call and move before the first turn that
    started after it, in their order in the provider's log. The agent speaks while its tools
    run, so a turn's start, not the time it was logged, puts it before or after a tool call. An
    equal or a missing time goes by the place in the log. A tool call with neither, or after
    every turn, comes last. The console shows the lines in this order too."""
    slots: list[list[RecordEvent]] = [[] for _ in range(len(turns) + 1)]
    for event in [*tools, *moves]:
        place = next(
            (index for index, turn in enumerate(turns) if comes_before(event, turn)), len(turns)
        )
        slots[place].append(event)
    lines: list[RecordLine] = []
    for index, slot in enumerate(slots):
        lines += sorted(slot, key=logged)
        if index < len(turns):
            lines.append(turns[index])
    return lines


def logged(event: RecordEvent) -> tuple[bool, int, bool, datetime]:
    """An event's order in the provider's log, else by time; one with neither keeps its place."""
    return (event.seq is None, event.seq or 0, event.at is None, event.at or NO_TIME)


def comes_before(event: RecordEvent, turn: RecordTurn) -> bool:
    if event.at is not None and turn.started_at is not None and event.at != turn.started_at:
        return event.at < turn.started_at
    if event.seq is not None and turn.seq is not None:
        return event.seq < turn.seq
    start = turn.started_at or turn.at
    return event.at is not None and start is not None and event.at <= start


def move_line(move: RecordMove, first: RecordMove | None) -> str:
    if move is first:
        return f"Agent started in node {move.node}"
    via = f", by {move.via}" if move.via else ""
    return f"Agent moved to node {move.node}{via}"


AGENT_SAID = "Agent said:"
"""How a record line of the agent's own words starts."""
AGENT_HEARD = "Agent heard:"
"""How a record line of the caller's words, as the agent's speech-to-text heard them, starts."""


def record_turn_line(turn: RecordTurn) -> str:
    said = AGENT_SAID if turn.role is Role.AGENT else AGENT_HEARD
    return f"{said} {turn.text}"


def record_tool_line(tool: RecordTool, serving: RecordMove | None) -> str:
    """A tool call of a node other than the one the last move came to names its node. A turn
    cannot: its line is the words the agent said, so a line before it names the node."""
    output = "no output reported" if tool.output is None else f"output {tool.output}"
    failed = ", and it failed" if tool.failed else ""
    node = f" in {node_name(tool.node)}" if serving and tool.node != serving.node else ""
    return f"Tool call{node}: {tool.name} {tool.arguments}, {output}{failed}"


def node_name(node: str | None) -> str:
    return f"node {node}" if node else "an unknown node"


def agent_record(stored: StoredRecord) -> list[str]:
    record = stored.record
    if record is None:
        return ["AGENT RECORD", "Yaksh could not read the agent's own record of this call."]
    label = RECORD_PROVIDERS[record.provider].label
    lines = [
        "AGENT RECORD",
        f"The agent's own record of this call, from {label}: the text it sent to its voice "
        '("Agent said"), what its speech-to-text heard ("Agent heard"), the tools it called and '
        "the values it saved. The transcript is the call as Yaksh's caller heard and spoke it. "
        "Judge the words the agent said from its own text here, the words the caller said from "
        "the transcript, and what reached the agent from what it heard. Quote a line by its "
        "number.",
    ]
    if record.moves:
        lines.append(
            "A node is a part of the agent that serves the call: a node, state or sub-agent, as "
            f'{label} names it. A line "Agent started in node" or "Agent moved to node" shows '
            "the node that serves the lines after it, up to the next such line. A tool call of "
            'another node names its node, and a line "The next line is from" names the node '
            "of the line after it. The Saved lines at the end are the values at the end of the "
            "call and belong to no node."
        )
    if stored.reason:
        lines.append(f"The record can be incomplete: it was {stored.reason}.")
    numbered = [f"[R{number}] {line}" for number, line in enumerate(record_lines(record), 1)]
    return lines + (numbered or ["The record has no lines."])


def with_item(view: str, item: str) -> str:
    return f"{view}\n\nITEM\n{item}"


def facts(found: list[Fact]) -> str:
    return "; ".join(f"{fact.name} = {fact.value}" for fact in found) or "none"


def who_called(view: CallView) -> str:
    if view.transport is Transport.TEXT:
        if view.direction is Direction.INBOUND:
            return "Yaksh's caller started the conversation with the agent, over text."
        return "The agent started the conversation with Yaksh's caller, over text."
    if view.direction is Direction.INBOUND:
        return (
            f"Yaksh called the agent at {view.agent_number or 'an unknown number'} "
            f"from {view.yaksh_number or 'an unknown number'}."
        )
    return (
        f"The agent called Yaksh's number {view.yaksh_number} "
        f"from {view.agent_caller_id or 'a number Plivo did not report'}."
    )


def answered(view: CallView) -> list[str]:
    """Who answered for Yaksh's caller, when its voicemail or call screener did."""
    answering = view.answering
    if view.answered_by is AnsweredBy.CALLER or answering is None:
        return []
    voicemail = VOICEMAIL_LABELS[answering.voicemail]
    if answering.voicemail is not Voicemail.MAILBOX_FULL:
        greeting = "its own greeting" if answering.greeting else "its standard greeting"
        voicemail = f"{voicemail}, {greeting}"
    if view.answered_by is AnsweredBy.VOICEMAIL:
        return [f"Answered by: the voicemail of Yaksh's caller ({voicemail})."]
    lines = [
        f"Answered by: the call screener of Yaksh's caller ({SCREENER_LABELS[answering.screener]})."
    ]
    if picked_up(view.events):
        lines.append("After the screener, Yaksh's caller picked up.")
    elif voicemail_answered(view.turns):
        lines.append(f"After the screener, the voicemail of Yaksh's caller answered ({voicemail}).")
    return lines


def how_it_ended(view: CallView) -> str:
    ended = ENDED_BY.get(view.end_reason, "The call ended") if view.end_reason else "The call ended"
    source = f" (Plivo hangup source: {view.hangup_source})" if view.hangup_source else ""
    length = "unknown" if view.talk_ms is None else f"{view.talk_ms / 1000:.1f} s"
    reason = view.end_reason.value if view.end_reason else "unknown"
    return f"{ended}{source}. End reason: {reason}. Call length: {length}."


def transcript(
    turns: list[Turn], events: list[WireEvent], stops: Mapping[int, LineStop]
) -> list[str]:
    """The numbered turns, with what the phone of Yaksh's caller did between them, and where
    each of its interruption lines came and when the agent's speech stopped after it, on lines
    that have no number, so a criterion's turn numbers stay the turns' own. A line that went
    out only in part is two turns; its note follows the first."""
    marks = sorted(
        (event for event in events if event.kind in BETWEEN_TURNS), key=lambda event: event.at_ms
    )
    played = {
        event.interruption.number: event
        for event in events
        if event.interruption is not None and event.interruption.reason is None
    }
    lines = []
    for number, turn in enumerate(turns, 1):
        while marks and marks[0].at_ms <= turn.started_at_ms:
            lines.append(mark_line(marks.pop(0)))
        lines.append(f"[{number}] {speaker(turn)}: {turn_evidence(turn)}")
        if turn.interruption is not None and turn.interruption in played:
            event = played.pop(turn.interruption)
            lines.append(interruption_line(event, turns, stops.get(turn.interruption)))
    return lines + [mark_line(event) for event in marks]


def fixed_lines(turns: list[Turn]) -> list[str]:
    """The interruption lines that Yaksh said for the caller are part of the caller's test, so
    the caller can follow one up, as when a line asks for another day."""
    said = [f'"{turn.text}"' for turn in turns if turn.interruption is not None]
    if not said:
        return []
    return [f"Fixed lines that Yaksh said for the caller while the agent spoke: {'; '.join(said)}."]


QUOTED_WORDS = 12
"""The most words of the agent before a line that the line's note quotes."""


def interruption_line(event: WireEvent, turns: list[Turn], stop: LineStop | None = None) -> str:
    """Where Yaksh's caller said a fixed line while the agent spoke, and when the agent's speech
    stopped after it. The line's turn comes after the whole agent turn that it interrupted, so
    without this the agent's answer to the line reads as if it came before the line. The
    interrupted turn is the stored agent turn that holds the start of the agent's turn, or else
    the line's start: the stored turn of a turn that a late transcript started begins at the
    agent's voice. Audio with no words, such as hold music, has no stored turn."""
    attempt = event.interruption
    assert attempt is not None
    held = holding(turns, attempt.turn_started_ms) or holding(turns, event.at_ms)
    words = attempt.words or ""
    if held is None and not words:
        where = (
            "Yaksh's caller said the fixed line above while the agent's side played sound with "
            "no words."
        )
    else:
        parts = []
        if held is not None:
            number, turn = held
            parts.append(f"{(event.at_ms - turn.started_at_ms) / 1000:.1f} s into turn [{number}]")
        if words:
            parts.append(f'after the words "{last_words(words)}"')
        where = (
            "Yaksh's caller said the fixed line above while the agent was speaking: "
            f"{', '.join(parts)}."
        )
    return f"({' '.join([where, *stop_sentence(stop)])})"


WINDOW = f"{STOP_WINDOW_MS / 1000:g} s"
UNMEASURED = {
    StopReason.RECORDING_ENDED: "the recording ended right after its speech",
    StopReason.MEDIA_GAP: "part of the agent's audio is missing",
    StopReason.NO_LINE_SPEECH: "the line's audio has no speech",
}
CUT_SHORT = {
    StopReason.RECORDING_ENDED: "and then the recording ended",
    StopReason.MEDIA_GAP: "and then part of its audio is missing",
}


def stop_sentence(stop: LineStop | None) -> list[str]:
    """When the agent's speech stopped after a line, in whole ms, so that a judge can hold it
    against a limit; nothing for a call that has no stop time."""
    if stop is None:
        return []
    match stop.result:
        case StopResult.STOPPED:
            return [
                f"The agent's speech stopped {stop.stop_ms} ms after the line's speech started."
            ]
        case StopResult.KEPT_TALKING if stop.at_least and stop.reason in CUT_SHORT:
            return [
                f"The agent did not stop within {WINDOW}: it spoke for at least {stop.stop_ms} ms "
                f"after the line's speech started, {CUT_SHORT[stop.reason]}."
            ]
        case StopResult.KEPT_TALKING:
            return [
                f"The agent did not stop within {WINDOW}: its speech went on for {stop.stop_ms} ms "
                "after the line's speech started."
            ]
        case StopResult.NOT_SPEAKING:
            return [
                "The agent was not speaking when the line's speech started, or its speech ended "
                f"less than {SOONEST_STOP_MS} ms after it: too soon to stop for the line."
            ]
        case StopResult.UNKNOWN:
            assert stop.reason is not None
            return [
                "Yaksh could not measure when the agent's speech stopped: "
                f"{UNMEASURED[stop.reason]}."
            ]


def holding(turns: list[Turn], ms: int | None) -> tuple[int, Turn] | None:
    """The numbered agent turn whose span holds the moment."""
    if ms is None:
        return None
    return next(
        (
            (number, turn)
            for number, turn in enumerate(turns, 1)
            if turn.role is Role.AGENT
            and turn.started_at_ms <= ms <= max(turn.started_at_ms, turn.ended_at_ms or 0)
        ),
        None,
    )


def last_words(words: str) -> str:
    split = words.split()
    if len(split) <= QUOTED_WORDS:
        return words
    return "…" + " ".join(split[-QUOTED_WORDS:])


BETWEEN_TURNS = frozenset(
    {WireEventKind.CALLER_SOUND, WireEventKind.HOLD_STARTED, WireEventKind.HANDOVER}
)


def mark_line(event: WireEvent) -> str:
    match event.kind:
        case WireEventKind.CALLER_SOUND:
            return f"(Voicemail: {event.detail or 'a tone'}.)"
        case WireEventKind.HOLD_STARTED:
            seconds = f" for {int(event.detail) / 1000:g} s" if event.detail else ""
            return f"(The call screener puts the agent on hold{seconds}.)"
        case _:
            return "(Yaksh's caller picks up.)"


def tool_line(tool: ToolItem) -> str:
    output = "no output reported" if tool.output is None else f"output {tool.output}"
    return f"    Tool call: {tool.name} {tool.arguments}, {output}"


def turn_evidence(turn: Turn) -> str:
    """What a judge can quote from a turn: its words and its tool calls."""
    return "\n".join([turn.text, *map(tool_line, turn.tools)])


def speaker(turn: Turn) -> str:
    if turn.role is Role.AGENT:
        return "Agent"
    name = "Caller" if turn.machine is None else RECORDED[turn.machine]
    marks = [
        mark
        for mark, applies in (
            ("recorded", turn.machine is not None),
            ("Yaksh's fixed line", turn.scripted),
            ("pressed on the phone keypad, not spoken", turn.dtmf),
            ("audio not confirmed played", turn.provenance is Provenance.UNCONFIRMED),
            (
                "cut off: the agent spoke over it, so part or none of it played",
                turn.provenance is Provenance.CUT,
            ),
        )
        if applies
    ]
    return f"{name} ({'; '.join(marks)})" if marks else name
