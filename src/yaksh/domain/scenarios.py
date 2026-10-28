import re
import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from yaksh.domain.canonical import canonical
from yaksh.domain.errors import ValidationError
from yaksh.domain.settings import MAX_DATA_SETS, CallerModel

Instructions = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
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
MAX_LINE_CHARS = 200
Line = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_LINE_CHARS)
]
"""A fixed line that the caller says without its model: its first words or an interruption."""


class Category(StrEnum):
    """What kind of situation a scenario tests. How the caller talks comes from the persona."""

    HAPPY_PATH = "happy_path"
    """A normal request with correct information."""
    MESSY_INPUT = "messy_input"
    """The caller gives wrong, partial, spelled-out or corrected information."""
    EDGE_CASE = "edge_case"
    """A request outside the agent's job, or one that pushes a rule: refusal or hand-off."""


def normalized(text: str) -> str:
    """How names and criteria are compared: spaces collapsed, lower case. lower(), not
    casefold(): the console checks names and placeholders the same way before it saves."""
    return " ".join(text.split()).lower()


class Fact(BaseModel):
    """A value the caller has and gives when the agent asks for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: FactName
    value: FactValue


MAX_DATA_SET_NAME_CHARS = 40
DataSetName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_DATA_SET_NAME_CHARS),
]
PLACEHOLDER = re.compile(r"\{\{([^{}]*)\}\}")


def default_data_set_name(number: int) -> str:
    return f"Data set {number}"


class DataSet(BaseModel):
    """One set of values a scenario plays: every data set of a scenario has the same fact
    names and agent data names, in the same order, with values of its own."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: DataSetName
    known_facts: list[Fact] = Field(default_factory=list, max_length=MAX_FACTS)
    agent_data: list[Fact] = Field(default_factory=list, max_length=MAX_FACTS)


MAX_INTERRUPTIONS = 3


def can_match(phrase: str) -> str:
    """A phrase needs a word or a number in the form that the match reads, or it would match
    every turn: "½" has a letter for `isalnum` but nothing in canonical form."""
    if not canonical(phrase):
        raise ValueError("a phrase needs at least one word or number")
    return phrase


Phrase = Annotated[Line, AfterValidator(can_match)]


class Interruption(BaseModel):
    """A fixed line the caller says while the agent is still speaking, on phone calls. A start
    is each new match of `agent_says` in the agent's words or, with no phrase, the start of each
    answer of the agent, from answer `from_answer` on. Each start opens one wait of `after_s`.
    The line plays when a wait ends with the agent speaking: in the turn of the match, or, with
    no phrase, in the agent turn of that answer that is open then, also after a pause in it. A
    line plays at most once. With a phrase, `after_s` and `from_answer` are 0 and 1 unless they
    are set; with no phrase, they are 2 and 2."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    say: Line
    agent_says: Phrase | None = None
    after_s: float = Field(default=2.0, ge=0, le=30)
    """Seconds from the start to the end of the wait: 2, or 0 with `agent_says`."""
    from_answer: int = Field(default=2, ge=1, le=100)
    """The first answer of the agent that can start a wait: 2, which skips the greeting, or 1
    with `agent_says`. Answer 1 is the agent's first speech while the persona is on the line.
    After the persona speaks or presses keys, the agent's next turn starts the next answer."""

    @model_validator(mode="before")
    @classmethod
    def phrase_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("agent_says"):
            return {"after_s": 0.0, "from_answer": 1, **data}
        return data

    def played(self, facts: list[Fact]) -> Interruption:
        """The interruption as a data set plays it, its placeholders filled with the set's
        values."""
        return self.model_copy(
            update={
                "say": filled(self.say, facts),
                "agent_says": filled(self.agent_says, facts) if self.agent_says else None,
            }
        )


def fact_names(text: str) -> list[str]:
    """The fact names that `{{name}}` placeholders in the text use, as written."""
    rest = PLACEHOLDER.sub("", text)
    if "{{" in rest or "}}" in rest:
        raise ValueError(f"unmatched braces in {text!r}")
    return [name.strip() for name in PLACEHOLDER.findall(text)]


def filled(text: str, facts: list[Fact]) -> str:
    """The text with each `{{fact name}}` replaced by the fact's value."""
    values = {normalized(fact.name): fact.value for fact in facts}
    return PLACEHOLDER.sub(lambda match: values[normalized(match.group(1))], text)


class PlayedScenario(BaseModel):
    """A scenario version as one data set plays it: placeholders filled with the set's values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_set_id: uuid.UUID
    data_set_name: str
    instructions: str
    known_facts: list[Fact]
    unknown_facts: list[str]
    criteria: list[str]
    agent_data: list[Fact]
    first_words: str | None
    caller: CallerModel | None
    interruptions: list[Interruption]


class ScenarioConfig(BaseModel):
    """What a scenario version pins. The instructions and the facts go to the caller. The
    criteria never do: they are what the agent must say or do on the call. Agent data goes only
    to the agent, in an outbound agent's trigger. Each data set is played as its own call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instructions: Instructions
    unknown_facts: list[FactName] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(min_length=1, max_length=10)
    data_sets: list[DataSet] = Field(min_length=1, max_length=MAX_DATA_SETS)
    first_words: Line | None = None
    """What the caller says first when it speaks first, without its model; None says its
    language's opening."""
    caller: CallerModel | None = None
    """The caller's model and reasoning effort for this scenario; None uses the settings'."""
    interruptions: list[Interruption] = Field(default_factory=list, max_length=MAX_INTERRUPTIONS)

    @property
    def known_fact_names(self) -> list[str]:
        return [fact.name for fact in self.data_sets[0].known_facts]

    @property
    def agent_data_names(self) -> list[str]:
        return [fact.name for fact in self.data_sets[0].agent_data]

    def stored(self) -> dict[str, Any]:
        """The config as a scenario and its versions keep it. With no interruptions it has no
        `interruptions` key: a process of an older version refuses a field that it does not
        know, and it must still read the scenario during a rolling deploy."""
        unknown_to_older = None if self.interruptions else {"interruptions"}
        return self.model_dump(mode="json", exclude=unknown_to_older)

    @model_validator(mode="after")
    def names_and_criteria_are_distinct(self) -> ScenarioConfig:
        known = [normalized(name) for name in self.known_fact_names]
        unknown = [normalized(name) for name in self.unknown_facts]
        agent = [normalized(name) for name in self.agent_data_names]
        for label, values in (
            ("known fact names", known),
            ("unknown facts", unknown),
            ("criteria", [normalized(text) for text in self.criteria]),
            ("agent data names", agent),
            ("data set names", [normalized(data_set.name) for data_set in self.data_sets]),
            ("data set ids", [str(data_set.id) for data_set in self.data_sets]),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        both = set(known) & set(unknown)
        if both:
            raise ValueError(f"a fact cannot be both known and unknown: {', '.join(sorted(both))}")
        for data_set in self.data_sets[1:]:
            if [normalized(fact.name) for fact in data_set.known_facts] != known:
                raise ValueError(
                    f'the data set "{data_set.name}" must have the same known facts, in the same '
                    "order, as the other data sets"
                )
            if [normalized(fact.name) for fact in data_set.agent_data] != agent:
                raise ValueError(
                    f'the data set "{data_set.name}" must have the same agent data, in the same '
                    "order, as the other data sets"
                )
        texts = [
            text for item in self.interruptions for text in (item.say, item.agent_says) if text
        ]
        for text in (self.instructions, *self.criteria, *texts):
            for name in fact_names(text):
                if normalized(name) not in known:
                    raise ValueError(
                        f"{{{{{name}}}}} names no known fact; use one of: "
                        f"{', '.join(self.known_fact_names) or 'none, add a known fact first'}"
                    )
        return self

    @model_validator(mode="after")
    def interruptions_fit_every_data_set(self) -> ScenarioConfig:
        """Each interruption's line and phrase stay within the line limit when a data set's facts
        fill them. It runs after the check above, so every placeholder names a known fact."""
        for data_set in self.data_sets:
            for number, item in enumerate(self.interruptions, 1):
                played = item.played(data_set.known_facts)
                for part, text in (("line", played.say), ("phrase", played.agent_says)):
                    if text is not None and len(text) > MAX_LINE_CHARS:
                        raise ValueError(
                            f"the {part} of interruption {number} is longer than "
                            f"{MAX_LINE_CHARS} characters with the facts of the data set "
                            f'"{data_set.name}"'
                        )
        return self

    def chosen(self, ids: Sequence[uuid.UUID] | None) -> list[DataSet]:
        """The data sets with these ids, in the order given, or all of them."""
        if ids is None:
            return self.data_sets
        by_id = {data_set.id: data_set for data_set in self.data_sets}
        missing = [str(data_set_id) for data_set_id in ids if data_set_id not in by_id]
        if missing:
            raise ValidationError(f"no data set {', '.join(missing)}; it may have been removed")
        return [by_id[data_set_id] for data_set_id in ids]

    def played(self, data_set_id: uuid.UUID) -> PlayedScenario:
        """The scenario as the data set plays it. A version keeps its data sets, so a
        conversation's data set is always there."""
        data_set = next(item for item in self.data_sets if item.id == data_set_id)
        facts = data_set.known_facts
        return PlayedScenario(
            data_set_id=data_set.id,
            data_set_name=data_set.name,
            instructions=filled(self.instructions, facts),
            known_facts=facts,
            unknown_facts=self.unknown_facts,
            criteria=[filled(text, facts) for text in self.criteria],
            agent_data=data_set.agent_data,
            first_words=self.first_words,
            caller=self.caller,
            interruptions=[item.played(facts) for item in self.interruptions],
        )


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
    forked_from_id: uuid.UUID | None = None
    """The scenario of the same agent this one was copied from."""

    def to_config(self) -> ScenarioConfig:
        return ScenarioConfig.model_validate(
            self.model_dump(exclude={*SCENARIO_LABELS, "persona_id", "forked_from_id"})
        )


class ScenarioUpdate(BaseModel):
    """A partial change; lists replace the stored list as a whole."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name | None = None
    category: Category | None = None
    description: Description | None = None
    persona_id: uuid.UUID | None = None
    instructions: Instructions | None = None
    unknown_facts: list[FactName] | None = Field(default=None, max_length=20)
    criteria: list[Criterion] | None = Field(default=None, min_length=1, max_length=10)
    data_sets: list[DataSet] | None = Field(default=None, min_length=1, max_length=MAX_DATA_SETS)
    first_words: Line | None = None
    """None clears it."""
    caller: CallerModel | None = None
    """None clears it: the scenario uses the settings' caller model."""
    interruptions: list[Interruption] | None = Field(default=None, max_length=MAX_INTERRUPTIONS)

    @field_validator(
        "name",
        "category",
        "persona_id",
        "instructions",
        "unknown_facts",
        "criteria",
        "data_sets",
        "interruptions",
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
