import uuid
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

Goal = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
MAX_FACT_NAME_CHARS = 80
MAX_FACTS = 30
"""The most known facts, and the most agent data values, that a scenario holds."""
FactName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_FACT_NAME_CHARS)
]
FactValue = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Criterion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
FirstWords = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Category(StrEnum):
    """What kind of situation a scenario tests. How the caller talks comes from the persona."""

    HAPPY_PATH = "happy_path"
    """A normal request with correct information."""
    MESSY_INPUT = "messy_input"
    """The caller gives wrong, partial, spelled-out or corrected information."""
    EDGE_CASE = "edge_case"
    """A request outside the agent's job, or one that pushes a rule: refusal or hand-off."""


def normalized(text: str) -> str:
    """How names and criteria are compared: spaces collapsed, case folded."""
    return " ".join(text.split()).casefold()


class Fact(BaseModel):
    """A value the caller has and gives when the agent asks for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: FactName
    value: FactValue


class ScenarioConfig(BaseModel):
    """What a scenario version pins. The goal and the facts go to the caller. The criteria never
    do: they are what the agent must say or do on the call. Agent data goes only to the agent,
    in an outbound agent's trigger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: Goal
    known_facts: list[Fact] = Field(default_factory=list, max_length=MAX_FACTS)
    unknown_facts: list[FactName] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(min_length=1, max_length=10)
    agent_data: list[Fact] = Field(default_factory=list, max_length=MAX_FACTS)
    first_words: FirstWords | None = None
    """What the caller says first when it speaks first, without its model; None says its
    language's opening."""

    @model_validator(mode="after")
    def names_and_criteria_are_distinct(self) -> ScenarioConfig:
        known = [normalized(fact.name) for fact in self.known_facts]
        unknown = [normalized(name) for name in self.unknown_facts]
        for label, values in (
            ("known fact names", known),
            ("unknown facts", unknown),
            ("criteria", [normalized(text) for text in self.criteria]),
            ("agent data names", [normalized(fact.name) for fact in self.agent_data]),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        both = set(known) & set(unknown)
        if both:
            raise ValueError(f"a fact cannot be both known and unknown: {', '.join(sorted(both))}")
        return self


SCENARIO_LABELS = frozenset({"name", "category", "description"})
"""Fields that describe a scenario without changing what a call uses, so not versioned."""
MAX_BULK = 500
"""Scenarios one bulk change takes."""


class ScenarioCreate(ScenarioConfig):
    name: Name
    category: Category = Category.HAPPY_PATH
    description: Description | None = None
    """Why the scenario exists; for people, never shown to the caller or the judge."""
    persona_id: uuid.UUID
    """The persona the scenario runs with. Not versioned: each conversation pins the persona
    and its version."""

    def to_config(self) -> ScenarioConfig:
        return ScenarioConfig.model_validate(
            self.model_dump(exclude={*SCENARIO_LABELS, "persona_id"})
        )


class ScenarioUpdate(BaseModel):
    """A partial change; lists replace the stored list as a whole."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name | None = None
    category: Category | None = None
    description: Description | None = None
    persona_id: uuid.UUID | None = None
    goal: Goal | None = None
    known_facts: list[Fact] | None = Field(default=None, max_length=MAX_FACTS)
    unknown_facts: list[FactName] | None = Field(default=None, max_length=20)
    criteria: list[Criterion] | None = Field(default=None, min_length=1, max_length=10)
    agent_data: list[Fact] | None = Field(default=None, max_length=MAX_FACTS)
    first_words: FirstWords | None = None
    """None clears it."""

    @field_validator(
        "name",
        "category",
        "persona_id",
        "goal",
        "known_facts",
        "unknown_facts",
        "criteria",
        "agent_data",
    )
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class ScenarioDelete(BaseModel):
    """Scenarios of one agent to delete together: all of them, or none if one is missing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK)


class AssignPersona(BaseModel):
    """One persona for several scenarios of one agent: all of them, or none if one is missing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK)
    persona_id: uuid.UUID
