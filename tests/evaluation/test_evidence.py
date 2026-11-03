import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from yaksh.domain.agent_records import (
    AgentRecord,
    RecordMove,
    RecordState,
    RecordTool,
    RecordTurn,
    StoredRecord,
)
from yaksh.domain.agents import Direction, Transport
from yaksh.domain.answering import AfterScreening, AnsweredBy, Answering, MachineLine, Voicemail
from yaksh.domain.conversations import (
    EndReason,
    InterruptionTry,
    Provenance,
    Role,
    ToolItem,
    TryReason,
    Turn,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.record_sources import RecordProvider
from yaksh.domain.scenarios import Fact
from yaksh.domain.stops import LineStop, StopReason, StopResult
from yaksh.evaluation.evidence import CallView, record_lines, render, with_item
from yaksh.evaluation.quotes import quote_problems
from yaksh.evaluation.sources import agent_line_problems
from yaksh.integrations.plivo_cx_runs import parse_run

FIXTURES = Path(__file__).parent / "fixtures"
LINES = [
    (Role.AGENT, "Thanks for calling Maple Dental, this is Ava. How can I help you today?"),
    (Role.CALLER, "Hi, I'd like to book a cleaning for next Tuesday afternoon. I'm a new patient."),
    (Role.AGENT, "Sure, I can help with that. Can I have your full name and date of birth?"),
    (Role.CALLER, "Jordan Lee. March fourteenth, nineteen ninety."),
    (
        Role.AGENT,
        "Thank you, Jordan. For Tuesday, October sixth, I have two thirty or four p.m. "
        "Which one works for you?",
    ),
    (Role.CALLER, "Two thirty, please. How much is the cleaning?"),
    (Role.AGENT, "A new patient cleaning is eighty dollars."),
    (Role.CALLER, "Okay, that's fine."),
    (
        Role.AGENT,
        "Great, you're booked for Tuesday, October sixth at two thirty p.m. "
        "Is there anything else?",
    ),
    (Role.CALLER, "No, that's all. Thank you!"),
    (Role.AGENT, "You're welcome, Jordan. See you on Tuesday. Goodbye!"),
]
MAPLE_DENTAL = CallView(
    brief="Books, moves and cancels dental appointments for Maple Dental.",
    agent_data=[],
    instructions="Book a cleaning for next Tuesday afternoon as a new patient.",
    known_facts=[
        Fact(name="full name", value="Jordan Lee"),
        Fact(name="date of birth", value="14 March 1990"),
        Fact(name="phone number", value="555 0142"),
    ],
    unknown_facts=["insurance member ID"],
    today=date(2026, 10, 1),
    time_zone="America/New_York",
    direction=Direction.INBOUND,
    transport=Transport.PHONE,
    agent_number="+15550100",
    yaksh_number="+15550177",
    agent_caller_id=None,
    hangup_source="Callee",
    end_reason=EndReason.AGENT_HANGUP,
    talk_ms=45_300,
    turns=[
        Turn(
            role=role,
            text=text,
            started_at_ms=index * 1000,
            ended_at_ms=index * 1000 + 500,
            provenance=(
                Provenance.UNCONFIRMED
                if index == 9
                else Provenance.TRANSMITTED
                if role is Role.CALLER
                else None
            ),
        )
        for index, (role, text) in enumerate(LINES)
    ],
)


def test_the_evidence_view_of_the_example_call_matches_its_golden_text() -> None:
    criterion = (
        "If the caller asks about the price, the agent says that a new patient cleaning costs $95."
    )

    rendered = with_item(render(MAPLE_DENTAL), f"Criterion: {criterion}")

    assert rendered + "\n" == (FIXTURES / "evidence_c0193.txt").read_text()


def test_the_view_marks_yaksh_lines_and_words_the_agent_spoke_over() -> None:
    turns = [
        Turn(role=Role.CALLER, text="Hello?", started_at_ms=0, ended_at_ms=400, scripted=True),
        Turn(role=Role.AGENT, text="Hi, this is RiseBird.", started_at_ms=500, ended_at_ms=900),
        Turn(
            role=Role.CALLER,
            text="March fourteenth",
            started_at_ms=1000,
            ended_at_ms=1500,
            provenance=Provenance.CUT,
        ),
    ]
    outbound = replace(
        MAPLE_DENTAL,
        direction=Direction.OUTBOUND,
        agent_number=None,
        agent_caller_id="+15550200",
        end_reason=None,
        hangup_source=None,
        talk_ms=None,
        turns=turns,
    )

    rendered = render(outbound)

    assert "The agent called Yaksh's number +15550177 from +15550200." in rendered
    assert "The call ended. End reason: unknown. Call length: unknown." in rendered
    assert "[1] Caller (Yaksh's fixed line): Hello?" in rendered
    assert (
        "[3] Caller (cut off: the agent spoke over it, so part or none of it played): "
        "March fourteenth"
    ) in rendered


def test_the_view_shows_where_each_interruption_line_came_in_the_agent_turn() -> None:
    agent = "Thank you, Jordan. Could you please tell me your age? Yes, there is no fee."
    turns = [
        Turn(role=Role.AGENT, text=agent, started_at_ms=1_000, ended_at_ms=6_000),
        Turn(
            role=Role.CALLER,
            text="Hold on, is there a fee?",
            started_at_ms=2_500,
            ended_at_ms=3_600,
            scripted=True,
            interruption=1,
        ),
        Turn(role=Role.AGENT, text="Sure.", started_at_ms=7_000, ended_at_ms=7_400),
        Turn(
            role=Role.CALLER,
            text="Mm-hmm.",
            started_at_ms=7_100,
            ended_at_ms=7_500,
            scripted=True,
            interruption=2,
        ),
    ]
    tries = [
        InterruptionTry(number=1, answer=2, turn_started_ms=1_000, words="Thank you, Jordan."),
        InterruptionTry(number=2, answer=3, turn_started_ms=7_000, words=""),
        InterruptionTry(number=2, answer=2, turn_started_ms=1_000, reason=TryReason.OTHER_LINE),
    ]
    events = [
        WireEvent(kind=WireEventKind.INTERRUPTION, at_ms=at_ms, interruption=attempt)
        for at_ms, attempt in zip([2_500, 7_100, 2_600], tries, strict=True)
    ]

    rendered = render(replace(MAPLE_DENTAL, turns=turns, events=events))

    assert (
        "[2] Caller (Yaksh's fixed line): Hold on, is there a fee?\n"
        "(Yaksh's caller said the fixed line above while the agent was speaking: 1.5 s into "
        'turn [1], after the words "Thank you, Jordan.".)\n'
        "[3] Agent: Sure."
    ) in rendered
    assert (
        "(Yaksh's caller said the fixed line above while the agent was speaking: 0.1 s into "
        "turn [3].)"
    ) in rendered
    assert (
        "Fixed lines that Yaksh said for the caller while the agent spoke: "
        '"Hold on, is there a fee?"; "Mm-hmm.".'
    ) in rendered, "in the CALLER section: the caller's test includes them"
    assert "Fixed lines" not in render(MAPLE_DENTAL)


def test_a_line_over_sound_with_no_words_or_after_a_late_transcript_is_still_placed() -> None:
    said = "Your first visit is one hundred and twenty dollars and that includes the cleaning and"
    turns = [
        Turn(role=Role.AGENT, text="Please hold.", started_at_ms=1_000, ended_at_ms=2_000),
        Turn(
            role=Role.CALLER,
            text="Sure, I can wait.",
            started_at_ms=3_000,
            ended_at_ms=4_000,
            scripted=True,
            interruption=1,
        ),
        Turn(role=Role.AGENT, text=f"{said} the x-rays.", started_at_ms=9_400, ended_at_ms=16_000),
        Turn(
            role=Role.CALLER,
            text="Sorry, how much?",
            started_at_ms=14_000,
            ended_at_ms=15_000,
            scripted=True,
            interruption=2,
        ),
    ]
    tries = [
        InterruptionTry(number=1, answer=2, turn_started_ms=2_500, words=""),
        InterruptionTry(number=2, answer=3, turn_started_ms=9_000, words=said),
    ]
    events = [
        WireEvent(kind=WireEventKind.INTERRUPTION, at_ms=at_ms, interruption=attempt)
        for at_ms, attempt in zip([3_000, 14_000], tries, strict=True)
    ]

    rendered = render(replace(MAPLE_DENTAL, turns=turns, events=events))

    assert (
        "[2] Caller (Yaksh's fixed line): Sure, I can wait.\n"
        "(Yaksh's caller said the fixed line above while the agent's side played sound with no "
        "words.)"
    ) in rendered, "hold music has no stored turn"
    assert (
        "(Yaksh's caller said the fixed line above while the agent was speaking: 4.6 s into "
        'turn [3], after the words "…is one hundred and twenty dollars and that includes the '
        'cleaning and".)'
    ) in rendered, "the stored turn starts at the agent's voice, after the late transcript"


def interrupted(*lines: Turn) -> tuple[list[Turn], list[WireEvent]]:
    """An agent turn and its lines, each line with the try that played it."""
    agent = Turn(role=Role.AGENT, text="Your booking is", started_at_ms=1_000, ended_at_ms=9_000)
    numbers = sorted({line.interruption for line in lines if line.interruption is not None})
    events = [
        WireEvent(
            kind=WireEventKind.INTERRUPTION,
            at_ms=2_000 * number,
            interruption=InterruptionTry(
                number=number, answer=1, turn_started_ms=1_000, words="Your booking is"
            ),
        )
        for number in numbers
    ]
    return [agent, *lines], events


def said(number: int, text: str, provenance: Provenance = Provenance.TRANSMITTED) -> Turn:
    return Turn(
        role=Role.CALLER,
        text=text,
        started_at_ms=2_000 * number,
        ended_at_ms=2_000 * number + 500,
        provenance=provenance,
        scripted=True,
        interruption=number,
    )


@pytest.mark.parametrize(
    ("stop", "sentence"),
    [
        (
            LineStop(number=1, line_ms=2_150, result=StopResult.STOPPED, stop_ms=841),
            "The agent's speech stopped 841 ms after the line's speech started.",
        ),
        (
            LineStop(number=1, line_ms=2_150, result=StopResult.KEPT_TALKING, stop_ms=9_662),
            "The agent did not stop within 2 s: its speech went on for 9662 ms after the line's "
            "speech started.",
        ),
        (
            LineStop(
                number=1,
                line_ms=2_150,
                result=StopResult.KEPT_TALKING,
                stop_ms=3_500,
                at_least=True,
                reason=StopReason.RECORDING_ENDED,
            ),
            "The agent did not stop within 2 s: it spoke for at least 3500 ms after the line's "
            "speech started, and then the recording ended.",
        ),
        (
            LineStop(
                number=1,
                line_ms=2_150,
                result=StopResult.KEPT_TALKING,
                stop_ms=3_000,
                at_least=True,
                reason=StopReason.MEDIA_GAP,
            ),
            "The agent did not stop within 2 s: it spoke for at least 3000 ms after the line's "
            "speech started, and then part of its audio is missing.",
        ),
        (
            LineStop(number=1, line_ms=2_150, result=StopResult.NOT_SPEAKING),
            "The agent was not speaking when the line's speech started.",
        ),
        (
            LineStop(
                number=1, line_ms=2_150, result=StopResult.UNKNOWN, reason=StopReason.MEDIA_GAP
            ),
            "Yaksh could not measure when the agent's speech stopped: part of the agent's audio "
            "is missing.",
        ),
        (
            LineStop(
                number=1,
                line_ms=2_150,
                result=StopResult.UNKNOWN,
                reason=StopReason.RECORDING_ENDED,
            ),
            "Yaksh could not measure when the agent's speech stopped: the recording ended right "
            "after its speech.",
        ),
        (
            LineStop(number=1, result=StopResult.UNKNOWN, reason=StopReason.NO_LINE_SPEECH),
            "Yaksh could not measure when the agent's speech stopped: the line's audio has no "
            "speech.",
        ),
    ],
)
def test_the_judges_read_when_the_agents_speech_stopped_after_a_line(
    stop: LineStop, sentence: str
) -> None:
    turns, events = interrupted(said(1, "Sorry, what time?"))

    rendered = render(replace(MAPLE_DENTAL, turns=turns, events=events, stops={1: stop}))

    assert (
        "[2] Caller (Yaksh's fixed line): Sorry, what time?\n"
        "(Yaksh's caller said the fixed line above while the agent was speaking: 1.0 s into "
        f'turn [1], after the words "Your booking is". {sentence})'
    ) in rendered


def test_a_line_that_went_out_in_part_gets_one_note() -> None:
    turns, events = interrupted(
        said(1, "Sorry,"), said(1, "what time was that?", Provenance.UNCONFIRMED)
    )
    stop = LineStop(number=1, line_ms=2_150, result=StopResult.STOPPED, stop_ms=788)

    rendered = render(replace(MAPLE_DENTAL, turns=turns, events=events, stops={1: stop}))

    assert rendered.count("Yaksh's caller said the fixed line above") == 1
    assert (
        "Sorry,\n(Yaksh's caller said the fixed line above while the agent was speaking: 1.0 s "
        'into turn [1], after the words "Your booking is". The agent\'s speech stopped 788 ms '
        "after the line's speech started.)\n[3]"
    ) in rendered


def test_a_line_whose_tries_did_not_play_gets_no_note() -> None:
    turns, _ = interrupted(said(1, "Sorry, what time?"))
    skipped = WireEvent(
        kind=WireEventKind.INTERRUPTION,
        at_ms=2_000,
        interruption=InterruptionTry(number=1, answer=1, reason=TryReason.AGENT_QUIET),
    )
    stop = LineStop(number=1, line_ms=2_150, result=StopResult.STOPPED, stop_ms=788)

    rendered = render(replace(MAPLE_DENTAL, turns=turns, events=[skipped], stops={1: stop}))

    assert "Yaksh's caller said the fixed line above" not in rendered
    assert "788 ms" not in rendered


def test_a_call_with_no_stop_time_keeps_the_note_of_where_the_line_came() -> None:
    turns, events = interrupted(said(1, "Sorry, what time?"))

    rendered = render(replace(MAPLE_DENTAL, turns=turns, events=events))

    assert 'after the words "Your booking is".)' in rendered
    assert "speech stopped" not in rendered


def test_a_text_conversation_has_its_own_transcript_note_and_no_phone_facts() -> None:
    view = render(
        replace(
            MAPLE_DENTAL,
            transport=Transport.TEXT,
            agent_number=None,
            yaksh_number=None,
            hangup_source=None,
        )
    )

    assert "over text, with no phone call" in view
    assert "speech-to-text" not in view
    assert "Yaksh's caller started the conversation with the agent, over text." in view
    assert "Yaksh called the agent" not in view


def test_a_judge_sees_and_can_quote_the_tools_of_a_text_turn() -> None:
    saved = ToolItem(id="c1", name="save_feedback", arguments='{"value": "liked it"}', output="ok")
    turns = [
        Turn(role=Role.AGENT, text="Thanks!", started_at_ms=0, ended_at_ms=1, tools=[saved]),
        Turn(role=Role.CALLER, text="Bye.", started_at_ms=2, ended_at_ms=3),
    ]
    view = render(replace(MAPLE_DENTAL, transport=Transport.TEXT, turns=turns))

    call = 'save_feedback {"value": "liked it"}'
    assert f"[1] Agent: Thanks!\n    Tool call: {call}, output ok\n[2]" in view
    assert quote_problems([{"turn": 1, "quote": call}], turns, tools=True) == []
    assert quote_problems([{"turn": 2, "quote": "save_feedback"}], turns, tools=True) != []
    assert quote_problems([{"turn": 1, "quote": call}], turns) != []


def test_a_judge_can_quote_a_lone_key_press_with_or_without_its_line_label() -> None:
    turns = [
        Turn(
            role=Role.AGENT, text="Press star to re-enter the card.", started_at_ms=0, ended_at_ms=1
        ),
        Turn(role=Role.CALLER, text="*", started_at_ms=2, ended_at_ms=2, dtmf=True),
    ]
    labeled = "[2] Caller (pressed on the phone keypad, not spoken): *"

    assert quote_problems([{"turn": 2, "quote": "*"}], turns, tools=True) == []
    assert quote_problems([{"turn": 2, "quote": labeled}], turns, tools=True) == []
    assert quote_problems([{"turn": 1, "quote": "*"}], turns, tools=True) != []


def test_a_quote_of_other_keys_is_not_a_quote_of_the_key_press() -> None:
    turns = [
        Turn(role=Role.CALLER, text="4111#", started_at_ms=0, ended_at_ms=0, dtmf=True),
        Turn(role=Role.CALLER, text="123", started_at_ms=1, ended_at_ms=1, dtmf=True),
    ]

    assert quote_problems([{"turn": 1, "quote": "41-11 #"}], turns) == []
    assert quote_problems([{"turn": 1, "quote": "4111*"}], turns) != []
    assert quote_problems([{"turn": 2, "quote": "123#"}], turns) != []


def outbound_call(*lines: tuple[Role, str, MachineLine | None], **fields: Any) -> CallView:
    outbound: dict[str, Any] = {
        "brief": "Calls patients to confirm their cleaning appointments for Maple Dental.",
        "direction": Direction.OUTBOUND,
        "agent_number": None,
        "agent_caller_id": "+15550200",
        "hangup_source": "Caller",
        "turns": [
            Turn(
                role=role,
                text=text,
                started_at_ms=index * 4000,
                ended_at_ms=index * 4000 + 3000,
                machine=machine,
            )
            for index, (role, text, machine) in enumerate(lines)
        ],
    }
    return replace(MAPLE_DENTAL, **{**outbound, **fields})


def test_the_evidence_marks_the_voicemails_recording_and_its_tone() -> None:
    view = outbound_call(
        (Role.CALLER, "Hi, you've reached Jordan. Leave a message.", MachineLine.GREETING),
        (Role.AGENT, "Hi Jordan, this is Ava from Maple Dental. Please call us back.", None),
        answered_by=AnsweredBy.VOICEMAIL,
        answering=Answering(voicemail=Voicemail.CARRIER, greeting="Hi, you've reached Jordan."),
        events=[WireEvent(kind=WireEventKind.CALLER_SOUND, at_ms=3500, detail="tone, 1 s")],
        end_reason=EndReason.VOICEMAIL_ENDED,
        hangup_source="Callee",
    )

    rendered = with_item(render(view), "Criterion: The agent leaves a call-back number.")

    assert rendered + "\n" == (FIXTURES / "evidence_voicemail.txt").read_text()


def test_a_recorded_line_that_did_not_play_in_full_says_so() -> None:
    view = outbound_call(
        (Role.CALLER, "Hi, you've reached Jordan. Leave a message.", MachineLine.GREETING),
        answered_by=AnsweredBy.VOICEMAIL,
        answering=Answering(),
    )
    greeting = view.turns[0].model_copy(update={"provenance": Provenance.UNCONFIRMED})

    rendered = render(replace(view, turns=[greeting]))

    assert "[1] Voicemail (recorded; audio not confirmed played): Hi, you've reached" in rendered


def test_the_evidence_tells_when_the_caller_picked_up_after_its_screener() -> None:
    view = outbound_call(
        (
            Role.CALLER,
            "Hi. If you record your name and reason for calling...",
            MachineLine.SCREENER,
        ),
        (Role.AGENT, "This is Ava from Maple Dental, about your cleaning.", None),
        (Role.CALLER, "Thanks. Please stay on the line.", MachineLine.SCREENER),
        (Role.CALLER, "Hello", None),
        (Role.AGENT, "Hi Jordan, can you still make Tuesday at two thirty?", None),
        answered_by=AnsweredBy.SCREENER,
        answering=Answering(after_screening=AfterScreening.PICKS_UP),
        events=[
            WireEvent(kind=WireEventKind.HOLD_STARTED, at_ms=11_000, detail="20000"),
            WireEvent(kind=WireEventKind.HANDOVER, at_ms=11_500),
        ],
    )

    rendered = with_item(render(view), "Criterion: The agent asks to confirm the appointment.")

    assert rendered + "\n" == (FIXTURES / "evidence_screened.txt").read_text()


def test_an_agent_line_said_while_a_tool_ran_comes_before_the_tools_result() -> None:
    def at(second: float) -> datetime:
        return datetime(2026, 10, 26, 14, 24, tzinfo=UTC) + timedelta(seconds=second)

    record = AgentRecord(
        provider=RecordProvider.PLIVO_CX,
        external_id="run-1",
        status="COMPLETED",
        complete=True,
        turns=[
            RecordTurn(role=Role.AGENT, text="One moment.", at=at(43.5), started_at=at(41.2)),
            RecordTurn(
                role=Role.AGENT, text="I could not move it.", at=at(54.3), started_at=at(44.7)
            ),
        ],
        tools=[RecordTool(name="reschedule", arguments="{}", output="failed", at=at(42.7))],
    )

    view = render(
        replace(MAPLE_DENTAL, record=StoredRecord(state=RecordState.FOUND, record=record))
    )

    assert (
        "[R1] Agent said: One moment.\n"
        "[R2] Tool call: reschedule {}, output failed\n"
        "[R3] Agent said: I could not move it."
    ) in view


NODES_RUN = Path(__file__).parents[1] / "integrations" / "fixtures" / "plivo_cx_run_nodes.json"


def nodes_record(change: Callable[[list[dict[str, Any]]], object] = list) -> AgentRecord:
    detail = json.loads(NODES_RUN.read_text())
    change(detail["logs"])
    return parse_run(detail, datetime.now(UTC))


def view_of(record: AgentRecord) -> str:
    return render(
        replace(MAPLE_DENTAL, record=StoredRecord(state=RecordState.FOUND, record=record))
    )


def test_the_judge_reads_each_move_before_the_lines_its_node_served() -> None:
    lines = record_lines(nodes_record())

    assert {index: line for index, line in enumerate(lines) if "node" in line[:30]} == {
        0: "Agent started in node Reception",
        4: "Agent moved to node Identity, by transfer_to_identity",
        13: "Agent moved to node Scheduling, by transfer_to_scheduling",
        22: "Agent moved to node End call, by end_call",
    }
    assert lines[5:7] == [
        "Agent said: I just need to confirm a couple of things first. Let me see if I can "
        "find your chart using the number you are calling from.",
        'Tool call: identify_patient {}, output {"ok": true, "data": {"candidates": [], '
        '"count": 0}, "error_code": null, "patient_safe_message": null}',
    ], "a line said while a tool ran comes before the tool"
    assert lines[23].startswith("Agent said: Your appointment at the Northgate office")
    assert lines[24].startswith("Saved: ")
    assert 'A line "Agent started in node"' in view_of(nodes_record())
    assert "Agent started in node" not in view_of(nodes_record().model_copy(update={"moves": []}))


def test_a_reply_the_end_node_did_not_give_names_its_own_node() -> None:
    lines = record_lines(nodes_record(lambda logs: logs.pop(71)))

    assert lines[22:24] == [
        "Agent moved to node End call, by end_call",
        "The next line is from node Scheduling",
    ]


def at(second: float) -> datetime:
    return datetime(2026, 10, 30, 11, 12, tzinfo=UTC) + timedelta(seconds=second)


@pytest.mark.parametrize(
    ("turn", "tool", "move"),
    [
        ({"started_at": at(2), "seq": 15}, {"at": at(2), "seq": 16}, {"at": at(2), "seq": 14}),
        ({"seq": 15}, {"seq": 16}, {"seq": 14}),
        ({"at": at(8), "seq": 15}, {"at": at(2), "seq": 16}, {"at": at(1), "seq": 14}),
        ({"started_at": at(2), "seq": 3}, {"at": at(3), "seq": 1}, {"at": at(1), "seq": 2}),
    ],
    ids=["same time", "no time", "speech start with no time", "log and time disagree"],
)
def test_tools_and_moves_take_their_place_by_time_then_by_the_log(
    turn: dict[str, Any], tool: dict[str, Any], move: dict[str, Any]
) -> None:
    record = AgentRecord(
        provider=RecordProvider.PLIVO_CX,
        external_id="run-1",
        status="COMPLETED",
        complete=True,
        turns=[RecordTurn(role=Role.AGENT, text="One moment.", node="Identity", **turn)],
        tools=[RecordTool(name="lookup", arguments="{}", node="Identity", **tool)],
        moves=[RecordMove(node="Identity", via="call", **move)],
    )

    assert record_lines(record) == [
        "Agent started in node Identity",
        "Agent said: One moment.",
        "Tool call: lookup {}, no output reported",
    ]


def test_a_tool_of_another_node_after_a_move_names_its_node() -> None:
    record = AgentRecord(
        provider=RecordProvider.PLIVO_CX,
        external_id="run-1",
        status="COMPLETED",
        complete=True,
        tools=[
            RecordTool(name="lookup", arguments="{}", at=at(3), seq=3, node="Reception"),
            RecordTool(name="balance", arguments="{}", at=at(4), seq=4),
        ],
        moves=[
            RecordMove(node="Reception", via="call", at=at(1), seq=1),
            RecordMove(node="Billing", via="transfer_to_billing", at=at(2), seq=2),
        ],
    )

    assert record_lines(record)[2:] == [
        "Tool call in node Reception: lookup {}, no output reported",
        "Tool call in an unknown node: balance {}, no output reported",
    ]


def test_a_judge_can_quote_a_move_but_not_as_words_the_agent_said() -> None:
    lines = record_lines(nodes_record())
    found = {"call_quote": None, "record_quote": {"line": 23, "quote": "End call, by end_call"}}

    assert agent_line_problems(found, [], lines) == []
    assert agent_line_problems(found, [], lines, words_only=True) == [
        'Record line R23 is not words the agent said. Quote an "Agent said" line.'
    ]
