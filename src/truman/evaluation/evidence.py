"""The evidence view: the one text every LLM judge and the review screen read about a call. It
leaves out what must not sway a judge: the caller's own reason for ending the call, the noise
setting, the agent's configuration and its documents. A change to the text is a new version."""

from dataclasses import dataclass
from datetime import date

from truman.domain.agents import Direction
from truman.domain.conversations import EndReason, Provenance, Role, Turn
from truman.domain.scenarios import Fact

EVIDENCE_VIEW_VERSION = 1

TRANSCRIPTION_NOTE = (
    "The agent's lines are Truman's speech-to-text of the agent's audio. Judge what was said, "
    'not the spelling: "for" can mean "four", and "to" can mean "two".'
)

ENDED_BY = {
    EndReason.AGENT_HANGUP: "The agent hung up",
    EndReason.CALLER_HANGUP: "Truman's caller hung up",
    EndReason.TURN_LIMIT: "Truman's caller hung up at the test's turn limit",
    EndReason.DURATION_LIMIT: "Truman ended the call at the test's time limit",
}


@dataclass(frozen=True)
class CallView:
    brief: str | None
    agent_data: list[Fact]
    goal: str
    known_facts: list[Fact]
    unknown_facts: list[str]
    today: date
    time_zone: str
    direction: Direction
    agent_number: str | None
    """The number Truman called; inbound agents only."""
    truman_number: str | None
    agent_caller_id: str | None
    """The number an outbound agent called from."""
    hangup_source: str | None
    end_reason: EndReason | None
    talk_ms: int | None
    turns: list[Turn]


def render(view: CallView) -> str:
    """The view without its item: what one request about every item of a call can share."""
    return "\n\n".join(
        [
            "\n".join(
                [
                    "AGENT",
                    f"Brief: {view.brief or 'none'}",
                    f"Agent data sent with this call: {facts(view.agent_data)}.",
                ]
            ),
            "\n".join(
                [
                    "CALLER",
                    f"Goal: {view.goal}",
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
            "\n".join(["CALL FACTS", who_called(view), how_it_ended(view)]),
            "\n".join(["TRANSCRIPT", TRANSCRIPTION_NOTE, *transcript(view.turns)]),
        ]
    )


def with_item(view: str, item: str) -> str:
    return f"{view}\n\nITEM\n{item}"


def facts(found: list[Fact]) -> str:
    return "; ".join(f"{fact.name} = {fact.value}" for fact in found) or "none"


def who_called(view: CallView) -> str:
    if view.direction is Direction.INBOUND:
        return (
            f"Truman called the agent at {view.agent_number or 'an unknown number'} "
            f"from {view.truman_number or 'an unknown number'}."
        )
    return (
        f"The agent called Truman's number {view.truman_number} "
        f"from {view.agent_caller_id or 'a number Plivo did not report'}."
    )


def how_it_ended(view: CallView) -> str:
    ended = ENDED_BY.get(view.end_reason, "The call ended") if view.end_reason else "The call ended"
    source = f" (Plivo hangup source: {view.hangup_source})" if view.hangup_source else ""
    length = "unknown" if view.talk_ms is None else f"{view.talk_ms / 1000:.1f} s"
    reason = view.end_reason.value if view.end_reason else "unknown"
    return f"{ended}{source}. End reason: {reason}. Call length: {length}."


def transcript(turns: list[Turn]) -> list[str]:
    return [f"[{number}] {speaker(turn)}: {turn.text}" for number, turn in enumerate(turns, 1)]


def speaker(turn: Turn) -> str:
    if turn.role is Role.AGENT:
        return "Agent"
    marks = [
        mark
        for mark, applies in (
            ("Truman's fixed line", turn.scripted),
            ("audio not confirmed played", turn.provenance is Provenance.UNCONFIRMED),
            ("not played: the agent spoke over it", turn.provenance is Provenance.CUT),
        )
        if applies
    ]
    return f"Caller ({'; '.join(marks)})" if marks else "Caller"
