"""Writing test scenarios from what Yaksh knows about an agent."""

import dataclasses
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from yaksh.domain.scenarios import Category

MAX_SCENARIOS = 20
MAX_PLANNER_CHARS = 800_000
"""About 200,000 tokens of brief, config and documents; more is refused, never cut."""


class GenerationMode(StrEnum):
    AGENT = "agent"
    """Scenarios for what the agent does, from its brief, config and knowledge base."""
    KNOWLEDGE_BASE = "knowledge_base"
    """Questions the chosen documents answer, and some they do not."""


class GenerationStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"
    """The console closed the stream; scenarios saved until then stay."""


class GenerateScenarios(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: GenerationMode = GenerationMode.AGENT
    count: int = Field(default=5, ge=1, le=MAX_SCENARIOS)
    instructions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    """The user's steering, such as "focus on rescheduling"."""
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    """The knowledge base documents to ask about; knowledge base mode only."""
    persona_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_SCENARIOS)
    """Spread over the new scenarios: a capability or question gets a persona again only after
    it got all of them."""

    @model_validator(mode="after")
    def documents_fit_mode(self) -> GenerateScenarios:
        if self.mode is GenerationMode.KNOWLEDGE_BASE and not self.document_ids:
            raise ValueError("pick at least one knowledge base document")
        if self.mode is GenerationMode.AGENT and self.document_ids:
            raise ValueError("documents are picked only in knowledge base mode")
        if len(set(self.persona_ids)) != len(self.persona_ids):
            raise ValueError("pick each persona once")
        return self


class Priority(StrEnum):
    CORE = "core"
    SECONDARY = "secondary"
    BOUNDARY = "boundary"
    """Something the agent must refuse or hand off."""


@dataclass(frozen=True)
class Capability:
    """Something the agent does, as the planner read it from the context."""

    name: str
    what_it_does: str
    priority: Priority
    quotes: tuple[str, ...]
    already_tested: bool


@dataclass(frozen=True)
class Question:
    """A question a caller could ask, with the documented answer, or none."""

    question: str
    answer: str | None
    document: str | None
    quote: str | None


@dataclass(frozen=True)
class Slot:
    """One scenario to write: what it tests, in which category, and for messy input slots how
    the caller gets the information wrong first."""

    category: Category
    capability: Capability | None = None
    question: Question | None = None
    entity_format: str | None = None
    variant: int = 0
    """How many earlier slots test the same thing in the same category."""


ENTITY_FORMATS = (
    "spells a name letter by letter",
    "says a number digit by digit",
    "gives a value, then corrects it",
    "gives part of a value, then the rest when asked",
    "gives a value in an unexpected format",
)
"""How a messy input caller gets information wrong first; voice agents fail most on these."""

MIN_QUOTE_CHARS = 12
MAX_REPEATS = 5
"""Slots for one subject in one category: the first, and a different variation for each
repeat."""


def category_quotas(count: int) -> dict[Category, int]:
    """About 30% messy input and 20% edge case, and always at least one happy path."""
    messy = int(count * 0.3 + 0.5)
    edge = int(count * 0.2 + 0.5)
    while messy + edge >= count and (messy or edge):
        if edge >= messy:
            edge -= 1
        else:
            messy -= 1
    return {
        Category.HAPPY_PATH: count - messy - edge,
        Category.MESSY_INPUT: messy,
        Category.EDGE_CASE: edge,
    }


def agent_slots(capabilities: list[Capability], count: int) -> list[Slot]:
    """Spread the scenarios over what the agent does, untested and core first. Edge case slots
    go to what the agent must refuse, or to a general out-of-scope request when none is known.
    Without anything the agent does, there is nothing to test. The same plan and count always
    give the same slots."""
    rank = {Priority.CORE: 0, Priority.SECONDARY: 1}
    doable = sorted(
        (c for c in capabilities if c.priority is not Priority.BOUNDARY),
        key=lambda c: (c.already_tested, rank[c.priority]),
    )
    if not doable:
        return []
    quotas = category_quotas(count)
    refusals = [c for c in capabilities if c.priority is Priority.BOUNDARY]
    slots: list[Slot] = []
    for index in range(quotas[Category.HAPPY_PATH] + quotas[Category.MESSY_INPUT]):
        messy = index >= quotas[Category.HAPPY_PATH]
        slots.append(
            Slot(
                category=Category.MESSY_INPUT if messy else Category.HAPPY_PATH,
                capability=doable[index % len(doable)],
                entity_format=ENTITY_FORMATS[index % len(ENTITY_FORMATS)] if messy else None,
            )
        )
    for index in range(quotas[Category.EDGE_CASE]):
        capability = refusals[index % len(refusals)] if refusals else None
        slots.append(Slot(category=Category.EDGE_CASE, capability=capability))
    return numbered(slots)


def question_slots(answered: list[Question], unanswered: list[Question], count: int) -> list[Slot]:
    """About 20% of the scenarios ask what the documents do not answer; the rest ask what
    they do, every third one with the caller getting a detail wrong first."""
    open_count = min(len(unanswered), int(count * 0.2 + 0.5) if answered else count)
    asked_count = count - open_count if answered else 0
    slots = [
        Slot(
            category=Category.MESSY_INPUT if index % 3 == 2 else Category.HAPPY_PATH,
            question=answered[index % len(answered)],
            entity_format=ENTITY_FORMATS[index % len(ENTITY_FORMATS)] if index % 3 == 2 else None,
        )
        for index in range(asked_count)
    ]
    slots += [
        Slot(category=Category.EDGE_CASE, question=unanswered[index]) for index in range(open_count)
    ]
    return numbered(slots)


def numbered(slots: list[Slot]) -> list[Slot]:
    """Each slot with how many earlier slots test the same thing in the same category, so the
    writer can take a different angle on a repeat. Repeats past MAX_REPEATS are left out: a
    small context gives fewer scenarios, not copies."""
    seen: dict[tuple[Category, Capability | Question | None], int] = {}
    result = []
    for slot in slots:
        key = (slot.category, slot.capability or slot.question)
        variant = seen.get(key, 0)
        seen[key] = variant + 1
        if variant < MAX_REPEATS:
            result.append(dataclasses.replace(slot, variant=variant))
    return result


def spread_personas(slots: Sequence[Slot], persona_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """A persona for each slot: the one used least so far with the slot's subject, then with
    its category, then overall, and the first listed on a tie. Each capability or question so
    meets every persona before it meets one twice, whatever the number of personas."""
    with_subject: Counter[tuple[Capability | Question | None, uuid.UUID]] = Counter()
    with_category: Counter[tuple[Category, uuid.UUID]] = Counter()
    overall: Counter[uuid.UUID] = Counter()
    chosen = []
    for slot in slots:
        subject = slot.capability or slot.question
        usage = [
            (with_subject[subject, p], with_category[slot.category, p], overall[p])
            for p in persona_ids
        ]
        persona = persona_ids[usage.index(min(usage))]
        with_subject[subject, persona] += 1
        with_category[slot.category, persona] += 1
        overall[persona] += 1
        chosen.append(persona)
    return chosen


def normalized_text(text: str) -> str:
    return " ".join(text.split()).lower()


def grounded(quote: str, context: str) -> bool:
    """Whether a quote the model gave appears in the context, spacing and case aside. Both
    are normalized_text; a very short quote proves nothing."""
    return len(quote) >= MIN_QUOTE_CHARS and quote in context
