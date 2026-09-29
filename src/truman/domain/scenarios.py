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
FactName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
FactValue = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Criterion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


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
    known_facts: list[Fact] = Field(default_factory=list, max_length=30)
    unknown_facts: list[FactName] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(min_length=1, max_length=10)
    agent_data: list[Fact] = Field(default_factory=list, max_length=30)

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


class ScenarioCreate(ScenarioConfig):
    name: Name

    def config(self) -> ScenarioConfig:
        return ScenarioConfig.model_validate(self.model_dump(exclude={"name"}))


class ScenarioUpdate(BaseModel):
    """A partial change; lists replace the stored list as a whole."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name | None = None
    goal: Goal | None = None
    known_facts: list[Fact] | None = Field(default=None, max_length=30)
    unknown_facts: list[FactName] | None = Field(default=None, max_length=20)
    criteria: list[Criterion] | None = Field(default=None, min_length=1, max_length=10)
    agent_data: list[Fact] | None = Field(default=None, max_length=30)

    @field_validator("name", "goal", "known_facts", "unknown_facts", "criteria", "agent_data")
    @classmethod
    def cannot_be_cleared(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
