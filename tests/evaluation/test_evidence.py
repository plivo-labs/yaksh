from dataclasses import replace
from datetime import date
from pathlib import Path

from yaksh.domain.agents import Direction, Transport
from yaksh.domain.conversations import EndReason, Provenance, Role, ToolItem, Turn
from yaksh.domain.scenarios import Fact
from yaksh.evaluation.evidence import CallView, render, with_item
from yaksh.evaluation.quotes import quote_problems

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
    assert "[3] Caller (not played: the agent spoke over it): March fourteenth" in rendered


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
