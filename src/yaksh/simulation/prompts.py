from collections.abc import Sequence
from datetime import date

from yaksh.domain.agents import Direction
from yaksh.domain.personas import PersonaConfig
from yaksh.domain.scenarios import Fact
from yaksh.simulation.languages import LANGUAGES, gender_line
from yaksh.simulation.templating import render


def spoken_date(day: date) -> str:
    return f"{day:%A}, {day.day} {day:%B %Y}"


def caller_instructions(
    persona: PersonaConfig,
    *,
    instructions: str,
    known_facts: Sequence[Fact],
    unknown_facts: Sequence[str],
    today: date,
    direction: Direction = Direction.INBOUND,
) -> str:
    """The caller's system prompt. It takes the scenario's instructions and facts, never the
    scenario itself, so the criteria cannot reach the caller."""
    language = [LANGUAGES[persona.language].instruction]
    forms = gender_line(persona.language, persona.voice_gender)
    if forms is not None:
        language.append(forms)
    return render(
        "caller.j2",
        outbound=direction is Direction.OUTBOUND,
        persona=persona.prompt.strip(),
        today=spoken_date(today),
        instructions=instructions.strip(),
        known_facts=known_facts,
        unknown_facts=unknown_facts,
        language=language,
    )
