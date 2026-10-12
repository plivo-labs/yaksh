"""Agent rules: checks that apply to every call of an agent, beside each scenario's criteria.
An LLM rule is judged like a criterion, after a gate that code decides; a phrase rule is a
required or forbidden phrase or pattern that code checks in the agent's lines."""

from enum import StrEnum
from typing import Annotated, Literal

import regex
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from yaksh.domain.evaluations import ItemRole

RuleKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")]
RuleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
RuleText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
MAX_PATTERN_CHARS = 200
MAX_RULES = 20


class RuleGate(StrEnum):
    """When an LLM rule can apply, decided in code before any model call."""

    ALWAYS = "always"
    AGENT_SPOKE = "agent_spoke"


class LlmRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["llm"] = "llm"
    key: RuleKey
    name: RuleName
    gate: RuleGate = RuleGate.AGENT_SPOKE
    applies_when: RuleText
    pass_when: RuleText
    fail_when: RuleText
    not_a_failure: RuleText | None = None
    role: ItemRole = ItemRole.REPORTING


class PhraseExpectation(StrEnum):
    REQUIRED = "required"
    FORBIDDEN = "forbidden"


class PhraseMatch(StrEnum):
    PHRASE = "phrase"
    """The words, after numbers, dates and times are written one way (canonical form)."""
    REGEX = "regex"


class PhraseWhere(StrEnum):
    FIRST_AGENT_TURN = "first_agent_turn"
    ANY_AGENT_TURN = "any_agent_turn"


def compiles(value: str) -> str:
    try:
        regex.compile(value)
    except regex.error as error:
        raise ValueError(f"not a regular expression: {error}") from error
    return value


class PhraseRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["phrase"] = "phrase"
    key: RuleKey
    name: RuleName
    expects: PhraseExpectation
    match: PhraseMatch = PhraseMatch.PHRASE
    value: Annotated[str, StringConstraints(min_length=1, max_length=MAX_PATTERN_CHARS)]
    where: PhraseWhere = PhraseWhere.ANY_AGENT_TURN
    role: ItemRole = ItemRole.REPORTING

    @model_validator(mode="after")
    def value_can_match(self) -> PhraseRule:
        """A phrase needs a word or a number, or it would match every turn; a pattern must
        compile."""
        if self.match is PhraseMatch.REGEX:
            compiles(self.value)
        elif not any(char.isalnum() for char in self.value):
            raise ValueError("a phrase needs at least one word or number")
        return self


AgentRule = Annotated[LlmRule | PhraseRule, Field(discriminator="kind")]


def distinct_keys(rules: list[AgentRule]) -> list[AgentRule]:
    keys = [rule.key for rule in rules]
    if len(set(keys)) < len(keys):
        raise ValueError("two rules have the same key")
    return rules


AgentRules = Annotated[list[AgentRule], Field(max_length=MAX_RULES), AfterValidator(distinct_keys)]
