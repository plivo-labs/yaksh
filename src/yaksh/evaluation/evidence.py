"""The evidence view: the one text every LLM judge and the review screen read about a call. It
leaves out what must not sway a judge: the caller's own reason for ending the call, the noise
setting, the agent's configuration and its documents. A change to the text is a new version."""

from dataclasses import dataclass, field
from datetime import date

from yaksh.domain.agent_records import AgentRecord, RecordTool, StoredRecord
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

EVIDENCE_VIEW_VERSION = 6

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
                *transcript(view.turns, view.events),
            ]
        ),
    ]
    if view.record is not None:
        sections.append("\n".join(agent_record(view.record)))
    return "\n\n".join(sections)


def record_lines(record: AgentRecord) -> list[str]:
    """The record's lines a judge can quote, numbered from 1 in the view: the values the agent
    saved, then its tool calls. What the agent heard is left out: it repeats the transcript."""
    return [f"Saved: {value.name} = {value.value}" for value in record.saved] + [
        record_tool_line(tool) for tool in record.tools
    ]


def record_tool_line(tool: RecordTool) -> str:
    output = "no output reported" if tool.output is None else f"output {tool.output}"
    failed = ", and it failed" if tool.failed else ""
    return f"Tool call: {tool.name} {tool.arguments}, {output}{failed}"


def agent_record(stored: StoredRecord) -> list[str]:
    record = stored.record
    if record is None:
        return ["AGENT RECORD", "Yaksh could not read the agent's own record of this call."]
    label = RECORD_PROVIDERS[record.provider].label
    lines = [
        "AGENT RECORD",
        f"The agent's own record of this call, from {label}: the values it saved and the "
        "tools it called. Quote a line by its number.",
    ]
    if stored.reason:
        lines.append(f"The record can be incomplete: it was {stored.reason}.")
    numbered = [f"[R{number}] {line}" for number, line in enumerate(record_lines(record), 1)]
    return lines + (numbered or ["The agent saved no values and called no tools."])


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


def transcript(turns: list[Turn], events: list[WireEvent]) -> list[str]:
    """The numbered turns, with what the phone of Yaksh's caller did between them on lines
    that have no number, so a criterion's turn numbers stay the turns' own."""
    marks = sorted(
        (event for event in events if event.kind in BETWEEN_TURNS), key=lambda event: event.at_ms
    )
    lines = []
    for number, turn in enumerate(turns, 1):
        while marks and marks[0].at_ms <= turn.started_at_ms:
            lines.append(mark_line(marks.pop(0)))
        lines.append(f"[{number}] {speaker(turn)}: {turn_evidence(turn)}")
    return lines + [mark_line(event) for event in marks]


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
            ("audio not confirmed played", turn.provenance is Provenance.UNCONFIRMED),
            ("not played: the agent spoke over it", turn.provenance is Provenance.CUT),
        )
        if applies
    ]
    return f"{name} ({'; '.join(marks)})" if marks else name
