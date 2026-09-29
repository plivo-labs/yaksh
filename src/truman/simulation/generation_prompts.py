"""What the scenario generator asks the model, and the strict schemas of its answers. The
schemas stay within Azure's strict mode: every field required, no counts or patterns (the
code checks those), at most five levels deep."""

from typing import Any

from truman.domain.agents import AgentConfig, Direction
from truman.domain.generation import Slot
from truman.domain.scenarios import Category


def strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}
FACTS = {"type": "array", "items": strict_object({"name": TEXT, "value": TEXT})}

CAPABILITIES_SCHEMA = strict_object(
    {
        "capabilities": {
            "type": "array",
            "items": strict_object(
                {
                    "name": TEXT,
                    "what_it_does": TEXT,
                    "priority": {"type": "string", "enum": ["core", "secondary", "boundary"]},
                    "quotes": TEXTS,
                    "already_tested": {"type": "boolean"},
                }
            ),
        }
    }
)

QUESTIONS_SCHEMA = strict_object(
    {
        "answered": {
            "type": "array",
            "items": strict_object(
                {"question": TEXT, "answer": TEXT, "document": TEXT, "quote": TEXT}
            ),
        },
        "unanswered": {"type": "array", "items": strict_object({"question": TEXT})},
    }
)

SCENARIO_SCHEMA = strict_object(
    {
        "name": TEXT,
        "description": TEXT,
        "goal": TEXT,
        "known_facts": FACTS,
        "unknown_facts": TEXTS,
        "criteria": TEXTS,
        "agent_data": FACTS,
    }
)

CAPABILITIES_SYSTEM = """\
You plan tests for a voice agent. Read everything about the agent below and list the \
distinct things a caller can get done with it, and the things it must refuse, redirect or \
hand off.

For each item give:
- name: a few words.
- what_it_does: one sentence.
- priority: "core" for the agent's main jobs, "secondary" for other jobs it handles, \
"boundary" for what it must refuse, redirect or hand off.
- quotes: one to three passages copied exactly, character for character, from the text \
below, that show the item exists. Items without such a passage are thrown away.
- already_tested: true when one of the existing scenarios already tests the item.

List only what the text shows; never invent a feature. At most 15 items, the main jobs \
first."""

QUESTIONS_SYSTEM = """\
You plan knowledge tests for a voice agent. From the documents below, list questions a real \
caller would ask on the phone that the documents answer, and a few that a caller would \
plausibly ask but the documents do not answer.

For each answered question give:
- question: as a caller would say it.
- answer: the documented answer, in a few words.
- document: the name of the document, exactly as given below.
- quote: a passage copied exactly, character for character, from that document, that \
contains the answer.

For each unanswered question give only the question.

Prefer what callers need: hours, prices, policies, eligibility, steps. At most 15 answered \
and 5 unanswered questions."""

SCENARIO_SYSTEM = """\
You write one test scenario for a voice agent. A simulated caller phones the agent and \
follows the scenario; a judge later checks the criteria against the call transcript.

Fields:
- name: names the situation in a few words, such as "Wrong date of birth, then corrected". \
Never a number.
- description: one sentence on what this scenario tests and which part of the agent it \
rests on.
- goal: what the caller wants and when the call is done, including the choices the caller \
makes ("take an evening slot next week; if there is none, keep the current booking"). No \
names, numbers or dates in the goal: those go in the facts.
- known_facts: every value the caller may be asked for, as name and value. The caller never \
invents a value, so a missing fact makes the call stall. Use realistic values. Write dates \
relative to today, such as "next Thursday".
- unknown_facts: names of things the caller does not have, when the test needs them.
- criteria: two to six checks. Each is a single claim about what the agent says or does, \
that a judge can confirm by quoting what the agent said. Name the expected values. Write a \
conditional check as "If ..., then ...". Never a check of what the caller says or does: the \
caller follows the goal. Never a check of anything the caller cannot hear, such as a \
database write, a webhook, or the name of a route, intent, node or tool.
- agent_data: see the agent section; otherwise an empty list.

Rules:
- The caller sees only the goal and the facts. In a recovery test, the goal must say exactly \
how the caller gets it wrong first, for example "give only the month and day of your birth \
date at first; give the year when asked".
- The caller never sees the criteria; do not repeat them in the goal or the facts.
- Make the scenario clearly different from the existing scenarios and from the others in \
this batch.
- One complication per scenario.
- No personality, mood or speaking style: those come from the caller persona.
- Test only what the text about the agent shows. A refusal or hand-off is a valid test; \
its criteria are the refusal or the hand-off.
- Write in English."""

ANGLES = (
    "the usual request",
    "the same need with a different choice or option",
    "the same need with an extra question along the way",
    "a caller who is unsure and needs the options explained",
    "a caller with a detail that changes the outcome",
)
"""Different takes on one area, one for each of the MAX_REPEATS slots it can get."""

CATEGORY_TASKS = {
    Category.HAPPY_PATH: "A normal request: the caller has the right information and cooperates.",
    Category.RECOVERY: "A recovery test: the caller gets information wrong first, and the "
    "agent must notice and recover.",
    Category.BOUNDARY: "A boundary test: the caller asks for something the agent must refuse, "
    "redirect or hand off.",
}


def agent_section(name: str, agent: AgentConfig, agent_data: list[str]) -> str:
    who = (
        "The caller phones the agent."
        if agent.direction is Direction.INBOUND
        else "The agent phones the caller; the caller answers."
    )
    first = "The agent speaks first." if agent.agent_speaks_first else "The caller speaks first."
    lines = [f"## Agent\n{name}. {who} {first}"]
    if agent_data:
        lines.append(
            "agent_data must hold a value for each of these, consistent with the known facts "
            "(the agent receives them before the call): " + ", ".join(agent_data) + "."
        )
    else:
        lines.append("agent_data must be an empty list.")
    return "\n".join(lines)


def context_sections(
    brief: str | None, config: str | None, documents: list[tuple[str, str]]
) -> str:
    sections = []
    if brief:
        sections.append(f"## Brief\n{brief}")
    if config:
        sections.append(f"## Configuration\n{config}")
    if documents:
        sections.append(
            "## Knowledge base\n" + "\n\n".join(f"### {name}\n{text}" for name, text in documents)
        )
    return "\n\n".join(sections)


def existing_section(existing: list[tuple[str, str]]) -> str:
    if not existing:
        return "## Existing scenarios\nNone."
    return "## Existing scenarios\n" + "\n".join(f"- {name}: {goal}" for name, goal in existing)


def instructions_section(instructions: str) -> str:
    return f"## Instructions from the user\n{instructions}" if instructions else ""


def batch_section(slot: Slot, slots: list[Slot]) -> str:
    """The other scenarios being written at the same time, so this one differs from them."""
    others = [
        f"- {other.category.value}: {subject(other)}, {angle(other)}"
        + (f"; the caller {other.entity_format}" if other.entity_format else "")
        for other in slots
        if other is not slot
    ]
    return "## Others in this batch\n" + "\n".join(others) if others else ""


def angle(slot: Slot) -> str:
    return ANGLES[slot.variant]


def areas_section(areas: list[str]) -> str:
    """What the agent handles, so a writer knows its job even for an out-of-scope test."""
    return "## What the agent handles\n" + "\n".join(f"- {area}" for area in areas)


def subject(slot: Slot) -> str:
    if slot.capability:
        return slot.capability.name
    if slot.question:
        return slot.question.question
    return "a request outside the agent's job"


def slot_section(slot: Slot) -> str:
    lines = [f"## What to test\n{CATEGORY_TASKS[slot.category]}"]
    if slot.capability:
        lines.append(f"Area: {slot.capability.name}: {slot.capability.what_it_does}")
        lines.append("It rests on:\n" + "\n".join(f'- "{q}"' for q in slot.capability.quotes))
    elif slot.question and slot.question.answer:
        lines.append(f'The caller asks: "{slot.question.question}"')
        lines.append(
            f'The documented answer is "{slot.question.answer}", from "{slot.question.document}": '
            f'"{slot.question.quote}". One criterion checks that the agent gives this answer.'
        )
    elif slot.question:
        lines.append(
            f'The caller asks: "{slot.question.question}" The documents do not answer it. The '
            "criteria check that the agent does not invent an answer, and says it does not "
            "know or offers a way to find out."
        )
    elif slot.category is Category.BOUNDARY:
        lines.append(
            "Pick a request a caller could plausibly make to this agent that is outside its job."
        )
    lines.append(f"Angle: {angle(slot)}.")
    if slot.entity_format:
        lines.append(f"How the caller gets it wrong first: the caller {slot.entity_format}.")
    return "\n".join(lines)
