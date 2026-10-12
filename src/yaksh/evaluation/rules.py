"""The parts of agent rules that code decides: an LLM rule's gate, and phrase rules."""

import time
from collections.abc import Sequence

import regex

from yaksh.domain.conversations import Role, Transcript, Turn
from yaksh.domain.evaluations import DecidedBy, Outcome
from yaksh.domain.rules import (
    LlmRule,
    PhraseExpectation,
    PhraseMatch,
    PhraseRule,
    PhraseWhere,
    RuleGate,
)
from yaksh.evaluation.canonical import canonical, contains
from yaksh.evaluation.judging import ItemResult
from yaksh.evaluation.verdicts import RULE


def gate_open(rule: LlmRule, transcript: Transcript) -> bool:
    if rule.gate is RuleGate.AGENT_SPOKE:
        return any(turn.role is Role.AGENT for turn in transcript.turns)
    return True


def gated(rule: LlmRule) -> ItemResult:
    """An LLM rule whose gate is shut: not applicable, with no model call."""
    return ItemResult(
        key=f"{RULE}{rule.key}",
        subject=rule.name,
        judge=None,
        decided_by=DecidedBy.CODE,
        role=rule.role,
        outcome=Outcome.NOT_APPLICABLE,
        answer={"gate": rule.gate.value},
    )


def phrase_item(rule: PhraseRule, turns: Sequence[Turn]) -> ItemResult:
    """A phrase matches as written or with numbers, dates and times in one written form, so
    "two thirty p.m." matches 2:30 pm. A forbidden phrase fails on any matching agent turn; a
    required one fails when no agent turn in its place matches. A pattern that runs past its
    time limit is an error, not a match."""
    agent = [number for number, turn in enumerate(turns, 1) if turn.role is Role.AGENT]
    looked_at = agent[:1] if rule.where is PhraseWhere.FIRST_AGENT_TURN else agent
    deadline = time.monotonic() + PATTERN_BUDGET_S
    try:
        matched = [
            number for number in looked_at if matches(rule, turns[number - 1].text, deadline)
        ]
    except TimeoutError:
        return ItemResult(
            key=f"{RULE}{rule.key}",
            subject=rule.name,
            judge=None,
            decided_by=DecidedBy.CODE,
            role=rule.role,
            outcome=Outcome.ERROR,
            error_reason="pattern_timeout",
        )
    found = bool(matched)
    passed = found if rule.expects is PhraseExpectation.REQUIRED else not found
    return ItemResult(
        key=f"{RULE}{rule.key}",
        subject=rule.name,
        judge=None,
        decided_by=DecidedBy.CODE,
        role=rule.role,
        outcome=Outcome.PASS if passed else Outcome.FAIL,
        answer={"matched_turns": matched},
    )


PATTERN_BUDGET_S = 0.5
"""How long one rule's pattern may run over all of a call's turns; the regex package stops it
then, where re would hold the event loop, and with it the lease's heartbeat, for as long as it
runs."""


def matches(rule: PhraseRule, text: str, deadline: float) -> bool:
    """A pattern matches the turn as written or in canonical form, so one with punctuation,
    such as \\$\\d+, still finds "$80"."""
    if rule.match is PhraseMatch.PHRASE:
        return contains(text, rule.value)
    for written in (text, canonical(text)):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError
        if regex.search(rule.value, written, regex.IGNORECASE, timeout=left):
            return True
    return False
