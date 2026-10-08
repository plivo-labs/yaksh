"""What the scenario generator asks the model, and the strict schemas of its answers. The
schemas stay within Azure's strict mode: every field required, no counts or patterns (the
code checks those), at most five levels deep."""

from typing import Any

from yaksha.domain.agents import AgentConfig
from yaksha.domain.generation import Slot
from yaksha.simulation.templating import render


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
        "instructions": TEXT,
        "known_facts": FACTS,
        "unknown_facts": TEXTS,
        "criteria": TEXTS,
        "agent_data": FACTS,
        "description": TEXT,
        "name": TEXT,
    }
)
"""The name and description come last, so the model names the scenario it wrote, not the
instructions it was given."""

CAPABILITIES_SYSTEM = render("capabilities_system.j2")
QUESTIONS_SYSTEM = render("questions_system.j2")
SCENARIO_SYSTEM = render("scenario_system.j2")


def context_text(brief: str, config: str | None, documents: list[tuple[str, str]]) -> str:
    """What the planner reads about the agent; its quotes must come from this text."""
    return render("context.j2", brief=brief, config=config, documents=documents)


def planner_input(
    name: str, agent: AgentConfig, context: str, existing: list[tuple[str, str]], instructions: str
) -> str:
    return render(
        "planner_input.j2",
        name=name,
        agent=agent,
        agent_data=[],
        context=context,
        existing=existing,
        instructions=instructions,
    )


def writer_input(
    name: str,
    agent: AgentConfig,
    agent_data: list[str],
    areas: list[str],
    slot: Slot,
    slots: list[Slot],
    existing: list[tuple[str, str]],
    instructions: str,
) -> str:
    """One writer's input: its slot, and the other slots written at the same time, so this
    scenario differs from them."""
    return render(
        "writer_input.j2",
        name=name,
        agent=agent,
        agent_data=agent_data,
        brief=agent.brief,
        areas=areas,
        slot=slot,
        slots=slots,
        existing=existing,
        instructions=instructions,
    )
