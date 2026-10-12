import uuid
from collections import Counter, defaultdict

import pytest

from yaksh.domain.generation import (
    ENTITY_FORMATS,
    MAX_REPEATS,
    Capability,
    Priority,
    Question,
    agent_slots,
    category_quotas,
    grounded,
    normalized_text,
    question_slots,
    spread_personas,
)
from yaksh.domain.scenarios import Category


def capability(name: str, priority: Priority, *, tested: bool = False) -> Capability:
    return Capability(name, f"{name}.", priority, ("a quote from the brief",), tested)


@pytest.mark.parametrize(
    ("count", "happy", "messy", "edge"),
    [(1, 1, 0, 0), (2, 1, 1, 0), (3, 1, 1, 1), (5, 2, 2, 1), (10, 5, 3, 2), (20, 10, 6, 4)],
)
def test_every_batch_has_a_happy_path_and_about_30_and_20_percent_of_the_rest(
    count: int, happy: int, messy: int, edge: int
) -> None:
    assert category_quotas(count) == {
        Category.HAPPY_PATH: happy,
        Category.MESSY_INPUT: messy,
        Category.EDGE_CASE: edge,
    }


def test_untested_core_work_comes_first_and_refusals_get_the_edge_case_slots() -> None:
    tested_core = capability("Book", Priority.CORE, tested=True)
    core = capability("Reschedule", Priority.CORE)
    secondary = capability("Directions", Priority.SECONDARY)
    refusal = capability("Medical advice", Priority.BOUNDARY)

    slots = agent_slots([tested_core, secondary, refusal, core], 5)

    assert [(slot.category, slot.capability) for slot in slots] == [
        (Category.HAPPY_PATH, core),
        (Category.HAPPY_PATH, secondary),
        (Category.MESSY_INPUT, tested_core),
        (Category.MESSY_INPUT, core),
        (Category.EDGE_CASE, refusal),
    ]
    assert [slot.entity_format for slot in slots[2:4]] == list(ENTITY_FORMATS[2:4])


def test_without_known_refusals_an_edge_case_slot_asks_for_something_out_of_scope() -> None:
    slots = agent_slots([capability("Book", Priority.CORE)], 3)

    assert (slots[-1].category, slots[-1].capability) == (Category.EDGE_CASE, None)


def test_about_a_fifth_of_knowledge_questions_are_ones_the_documents_do_not_answer() -> None:
    answered = [Question(f"Q{n}", "A", "FAQ", "a quote") for n in range(4)]
    unanswered = [Question("Do you validate parking?", None, None, None)]

    slots = question_slots(answered, unanswered, 5)
    only_open = question_slots([], unanswered, 5)

    assert [slot.category for slot in slots] == [
        Category.HAPPY_PATH,
        Category.HAPPY_PATH,
        Category.MESSY_INPUT,
        Category.HAPPY_PATH,
        Category.EDGE_CASE,
    ]
    assert [slot.question for slot in slots[:4]] == answered
    assert [slot.category for slot in only_open] == [Category.EDGE_CASE]


def test_a_quote_counts_only_when_the_context_has_it_and_it_is_not_tiny() -> None:
    context = normalized_text("Clinic hours are 9 to 5,\n  Monday to Friday.")

    assert grounded(normalized_text("clinic hours are 9 to 5, MONDAY"), context)
    assert not grounded(normalized_text("Clinic hours are 8 to 6"), context)
    assert not grounded(normalized_text("Clinic"), context)


def test_a_small_context_gives_fewer_scenarios_rather_than_repeats() -> None:
    agent_plan = agent_slots([capability("Book", Priority.CORE)], 20)
    knowledge_plan = question_slots([Question("Q", "A", "FAQ", "a quote")], [], 20)

    for slots in (agent_plan, knowledge_plan):
        variants = [(slot.category, slot.variant) for slot in slots]
        assert len(variants) == len(set(variants))
        assert max(slot.variant for slot in slots) == MAX_REPEATS - 1
    assert len(agent_plan) == 14


def test_each_capability_meets_every_persona_whatever_the_counts() -> None:
    book, cancel = capability("Book", Priority.CORE), capability("Cancel", Priority.CORE)
    slots = agent_slots([book, cancel], 5)
    personas = [uuid.UUID(int=1), uuid.UUID(int=2)]

    chosen = spread_personas(slots, personas)

    met: dict[Capability | None, set[uuid.UUID]] = defaultdict(set)
    for slot, persona in zip(slots, chosen, strict=True):
        met[slot.capability].add(persona)
    assert met[book] == met[cancel] == set(personas)
    assert sorted(Counter(chosen).values()) == [2, 3]
