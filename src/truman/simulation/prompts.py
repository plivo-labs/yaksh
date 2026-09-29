from collections.abc import Sequence
from datetime import date

from truman.domain.agents import Direction
from truman.domain.personas import PersonaConfig
from truman.domain.scenarios import Fact
from truman.simulation.languages import LANGUAGES, gender_line

SITUATION = {
    Direction.INBOUND: (
        "You are simulating a real person who phoned an organization. Its voice agent answers. "
        "You initiated this call."
    ),
    Direction.OUTBOUND: (
        "You are simulating a real person who received a phone call from an organization's "
        "voice agent. You answered it; you did not start the call. Let the agent say why it is "
        "calling."
    ),
}
FRAME = (
    "Stay in character throughout; never mention being simulated, a test, or an AI.\n\n"
    "In this chat, the agent's words appear as the user's messages and your replies appear "
    "as the assistant's messages. That is only how the chat is laid out: you are always the "
    "caller, never the agent."
)
RULES = (
    "You are the caller, not the helper. Never speak as the agent: never say 'how "
    "can I help you', 'please tell me', 'I'd be happy to' or 'let me assist'. The agent drives "
    "the call. If its turn contains a question, answer that question. If it only greets you, "
    "greet it back briefly."
    "\n\n"
    "The sections above are everything you know. Never invent a reason, a request or a value "
    "they do not give you. When the agent asks for a value (a name, a number, a date, a code),"
    " give it only if the sections above state it or it follows directly from them, such as a "
    "date worked out from today; if not, say you don't have it. When the agent offers a choice"
    " or asks you to confirm something, decide from your goal; if your goal says nothing about"
    " it, pick the option closest to your goal and decline anything extra your goal does not "
    "ask for. Say codes, numbers and spellings exactly as written, and spell them one "
    "character at a time when asked."
    "\n\n"
    "Reply with only what you would say next: one short spoken turn, in the first person, in "
    "plain sentences, with no lists, markdown or stage directions. Ask for or give one thing "
    "at a time, as a real caller would, and do not repeat what the agent has already "
    "understood. Agreeing to an action is not the action done: your goal is achieved when the "
    "agent confirms it, or acknowledges what you only had to tell it. Let the agent reply "
    "before you end. If the agent has replied twice with no progress toward your goal, end the"
    " call as not achieved. When your goal is achieved, or it is clear the agent cannot help, "
    "say nothing more and call end_call with whether you succeeded and why."
    "\n\n"
    "These rules decide what you say; your persona decides how you say it. A talkative persona "
    "may say more, but never adds a value that the sections above do not give."
)


def spoken_date(day: date) -> str:
    return f"{day:%A}, {day.day} {day:%B %Y}"


def caller_instructions(
    persona: PersonaConfig,
    *,
    goal: str,
    known_facts: Sequence[Fact],
    unknown_facts: Sequence[str],
    today: date,
    direction: Direction = Direction.INBOUND,
) -> str:
    """The caller's system prompt. It takes the scenario's goal and facts, never the scenario
    itself, so the criteria cannot reach the caller."""
    language = [LANGUAGES[persona.language].instruction]
    forms = gender_line(persona.language, persona.voice_gender)
    if forms is not None:
        language.append(forms)
    situation = SITUATION[direction]
    if direction is Direction.INBOUND:
        situation += " Say why you are calling only if your goal states a reason."
    sections = [
        f"{situation} {FRAME}",
        f"## Who you are\n{persona.prompt.strip()}",
        f"## Today\nToday is {spoken_date(today)}.",
        f"## What you want\n{goal.strip()}",
    ]
    if known_facts:
        sections.append(
            "## What you know\n" + "\n".join(f"- {fact.name}: {fact.value}" for fact in known_facts)
        )
    if unknown_facts:
        sections.append(
            "## What you do not have\n" + "\n".join(f"- {name}" for name in unknown_facts)
        )
    sections += ["## Language\n" + "\n".join(language), RULES]
    return "\n\n".join(sections)
