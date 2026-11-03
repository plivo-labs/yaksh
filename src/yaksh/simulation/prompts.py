from collections.abc import Sequence
from datetime import date

from yaksh.domain.agents import Direction
from yaksh.domain.languages import Language
from yaksh.domain.personas import PersonaConfig
from yaksh.domain.scenarios import Fact
from yaksh.domain.voices import VoiceGender
from yaksh.simulation.languages import LANGUAGES, gender_line
from yaksh.simulation.templating import render

SWITCHING = (
    "Switch between these languages as your persona and your instructions say. If they do not "
    "say when, switch at least once during the call."
)


def spoken_date(day: date) -> str:
    return f"{day:%A}, {day.day} {day:%B %Y}"


def speaking(language: Language, gender: VoiceGender | None) -> list[str]:
    """How the caller speaks one language: its line, and its word forms where they follow the
    voice."""
    forms = gender_line(language, gender)
    return [LANGUAGES[language].instruction, *([] if forms is None else [forms])]


def language_lines(persona: PersonaConfig) -> list[str]:
    """The prompt's language lines. A caller of one language gets only how to speak it; one
    with additional languages also learns its main one and that it switches."""
    if not persona.additional_languages:
        return speaking(persona.language, persona.voice_gender)
    *others, last = [language.label for language in persona.additional_languages]
    also = f"{', '.join(others)} and {last}" if others else last
    return [
        f"Your main language is {persona.language.label}. You also speak {also}.",
        SWITCHING,
        *(
            f"- {language.label}: {' '.join(speaking(language, persona.voice_gender))}"
            for language in persona.languages
        ),
    ]


def caller_instructions(
    persona: PersonaConfig,
    *,
    instructions: str,
    known_facts: Sequence[Fact],
    unknown_facts: Sequence[str],
    today: date,
    direction: Direction = Direction.INBOUND,
    over_text: bool = False,
) -> str:
    """The caller's system prompt. It takes the scenario's instructions and facts, never the
    scenario itself, so the criteria cannot reach the caller."""
    return render(
        "caller.j2",
        outbound=direction is Direction.OUTBOUND,
        persona=persona.prompt.strip(),
        today=spoken_date(today),
        instructions=instructions.strip(),
        known_facts=known_facts,
        unknown_facts=unknown_facts,
        language=language_lines(persona),
        over_text=over_text,
    )
