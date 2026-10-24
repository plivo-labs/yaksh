import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from tests.conftest import Scripted
from yaksh.diagnostics import describe_exception
from yaksh.domain.conversations import Role, Transcript, Turn, WireEvent, WireEventKind
from yaksh.domain.evaluations import DecidedBy, ItemRole, Outcome, UnsureKind, Verdict
from yaksh.domain.language_models import ModelCallError
from yaksh.domain.rules import LlmRule, PhraseRule, RuleGate
from yaksh.evaluation import judging
from yaksh.evaluation.criteria import judge_criterion, judge_rule
from yaksh.evaluation.judging import JudgeUnavailable
from yaksh.evaluation.rules import gate_open, phrase_item
from yaksh.evaluation.verdicts import verdict

TURNS = [
    Turn(role=Role.AGENT, text="Thanks for calling Maple Dental.", started_at_ms=0, ended_at_ms=1),
    Turn(role=Role.CALLER, text="How much is a cleaning?", started_at_ms=2, ended_at_ms=3),
    Turn(
        role=Role.AGENT, text="A cleaning is ninety five dollars.", started_at_ms=4, ended_at_ms=5
    ),
    Turn(role=Role.CALLER, text="My number is 555 0142.", started_at_ms=6, ended_at_ms=7),
    Turn(
        role=Role.AGENT,
        text="I have five five five, oh one four two. Goodbye!",
        started_at_ms=8,
        ended_at_ms=9,
    ),
]


def answer(verdict: str = "pass", **fields: Any) -> dict[str, Any]:
    return {
        "evidence": [{"turn": 3, "quote": "ninety five dollars"}],
        "record_evidence": [],
        "absence": False,
        "absence_turns": None,
        "reasoning": "It said the price.",
        "verdict": verdict,
        "kind": None,
    } | fields


async def criterion(
    model: Scripted, retry_later: bool = True, text: str = "Says the price."
) -> Any:
    return await judge_criterion(
        model,
        "VIEW",
        TURNS,
        1,
        text,
        record_lines=[],
        slots=asyncio.Semaphore(4),
        retry_later=retry_later,
    )


async def test_a_quote_in_another_written_form_counts_and_a_wrong_turn_gets_one_re_ask() -> None:
    spoken = Scripted(answer(evidence=[{"turn": 5, "quote": "555 0142"}]))
    corrected = Scripted(
        answer(evidence=[{"turn": 2, "quote": "ninety five dollars"}]), answer("fail")
    )
    twice_wrong = Scripted(
        answer(evidence=[{"turn": 9, "quote": "x"}]), answer(evidence=[{"turn": 9, "quote": "x"}])
    )

    first, second, third = (
        await criterion(spoken),
        await criterion(corrected),
        await criterion(twice_wrong),
    )

    assert (first.outcome, first.re_asks, len(first.attempts)) == (Outcome.PASS, 0, 1)
    assert (second.outcome, second.re_asks) == (Outcome.FAIL, 1)
    assert (
        "is not in turn 2" in corrected.requests[1]
        and "YOUR EARLIER ANSWER" in corrected.requests[1]
    )
    assert (third.outcome, third.error_reason) == (Outcome.ERROR, "invalid_evidence")
    assert (first.decided_by, first.role, first.key) == (
        DecidedBy.LLM,
        ItemRole.DECIDING,
        "criterion-1",
    )


async def test_an_absence_claim_that_stops_early_is_asked_about_once_and_then_stands() -> None:
    early = answer("fail", evidence=[], absence=True, absence_turns={"first": 1, "last": 3})
    model = Scripted(early, early)

    found = await criterion(model, text="Asks for the phone number before quoting a price.")

    assert (found.outcome, found.re_asks, found.error_reason) == (Outcome.FAIL, 1, None)
    assert "Check turns 4 to 5 too" in model.requests[1]


async def test_an_unsure_answer_needs_its_kind_and_keeps_it() -> None:
    model = Scripted(answer("unsure"), answer("unsure", kind="hidden_action"))

    found = await criterion(model, text="The booking is saved.")

    assert (found.outcome, found.unsure_kind, found.re_asks) == (
        Outcome.UNSURE,
        UnsureKind.HIDDEN_ACTION,
        1,
    )


@pytest.mark.usefixtures("no_waits")
@pytest.mark.parametrize(
    ("error", "retry_later", "reason"),
    [
        (ModelCallError("timed out", temporary=True), False, "judge_unavailable"),
        (ModelCallError("the model refused: no", temporary=False), True, "judge_failed"),
    ],
)
async def test_a_judge_failure_is_the_items_error_when_it_cannot_wait(
    error: ModelCallError, retry_later: bool, reason: str
) -> None:
    found = await criterion(Scripted(*[error] * 4), retry_later=retry_later)

    assert (found.outcome, found.error_reason, found.attempts[0].error) == (
        Outcome.ERROR,
        reason,
        str(error),
    )


@pytest.fixture
def no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judging, "WAITS_S", (0.0, 0.0, 0.0))


@pytest.mark.usefixtures("no_waits")
async def test_a_temporary_failure_is_asked_again_and_then_puts_the_evaluation_off() -> None:
    busy = ModelCallError("HTTP 429", temporary=True)
    recovered = await criterion(Scripted(busy, busy, answer()))

    with pytest.raises(JudgeUnavailable):
        await criterion(Scripted(busy, busy, busy, busy))

    assert (recovered.outcome, len(recovered.attempts)) == (Outcome.PASS, 3)


async def test_an_agent_rule_that_does_not_apply_is_not_applicable_whatever_it_says() -> None:
    rule = LlmRule(
        key="dob",
        name="Never says the date of birth",
        applies_when="the caller gives a date of birth",
        pass_when="the agent never says it back",
        fail_when="the agent says it back",
    )

    found = await judge_rule(
        Scripted({"applies": False} | answer("pass")),
        "VIEW",
        TURNS,
        rule,
        record_lines=[],
        slots=asyncio.Semaphore(1),
        retry_later=True,
    )

    assert (found.key, found.outcome, found.role) == (
        "rule-dob",
        Outcome.NOT_APPLICABLE,
        ItemRole.REPORTING,
    )


def phrase(**fields: Any) -> PhraseRule:
    return PhraseRule.model_validate({"key": "p", "name": "Phrase"} | fields)


def test_phrase_rules_match_spoken_numbers_in_their_place() -> None:
    def outcome(rule: PhraseRule) -> Outcome:
        return phrase_item(rule, TURNS).outcome

    assert (
        outcome(phrase(expects="required", value="Maple Dental", where="first_agent_turn"))
        is Outcome.PASS
    )
    assert (
        outcome(phrase(expects="required", value="goodbye", where="first_agent_turn"))
        is Outcome.FAIL
    )
    assert outcome(phrase(expects="required", value="$95")) is Outcome.PASS
    assert (
        outcome(phrase(expects="forbidden", match="regex", value=r"\b555\s?0142\b")) is Outcome.FAIL
    )
    assert outcome(phrase(expects="forbidden", value="guarantee")) is Outcome.PASS
    assert phrase_item(phrase(expects="required", value="0142"), TURNS).answer == {
        "matched_turns": [5]
    }


def test_a_rule_gate_is_decided_from_the_call_record() -> None:
    def gate(kind: RuleGate) -> Callable[[Transcript], bool]:
        rule = LlmRule(key="g", name="G", gate=kind, applies_when="a", pass_when="b", fail_when="c")
        return lambda transcript: gate_open(rule, transcript)

    silent = Transcript(wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)])
    spoke = Transcript(turns=TURNS)

    assert gate(RuleGate.ALWAYS)(Transcript())
    assert gate(RuleGate.AGENT_SPOKE)(spoke) and not gate(RuleGate.AGENT_SPOKE)(silent)


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (["pass", "pass", "fail", "not_applicable", "hidden_action"], Verdict.FAIL),
        (["pass", "pass", "pass", "not_applicable", "hidden_action"], Verdict.PASS),
        (
            ["pass", "not_confirmed_played", "pass", "not_applicable", "hidden_action"],
            Verdict.NOT_SCORED,
        ),
        (["pass", "blocked", "pass", "not_applicable", "hidden_action"], Verdict.NOT_SCORED),
        (["pass", "error", "fail", "not_applicable", "hidden_action"], Verdict.FAIL),
        (["not_applicable", "not_applicable", "hidden_action"], Verdict.NOT_SCORED),
        (["pass", "pass", "pending", "not_applicable"], Verdict.NOT_SCORED),
    ],
)
def test_the_verdict_follows_the_worked_examples(outcomes: list[str], expected: Verdict) -> None:
    def item(name: str) -> tuple[Outcome, UnsureKind | None]:
        if name in UnsureKind:
            return Outcome.UNSURE, UnsureKind(name)
        return Outcome(name), None

    assert verdict(item(name) for name in outcomes) is expected


def test_a_pattern_with_punctuation_matches_the_turn_as_written() -> None:
    turns = [Turn(role=Role.AGENT, text="Your SSN is 123-45-6789.", started_at_ms=0, ended_at_ms=1)]

    found = phrase_item(
        phrase(expects="forbidden", match="regex", value=r"\d{3}-\d{2}-\d{4}"), turns
    )

    assert found.outcome is Outcome.FAIL
    with pytest.raises(ValidationError, match="at least one word or number"):
        phrase(expects="required", value="!!!")


async def test_a_pass_that_rests_on_an_absence_is_asked_about_the_turns_it_left_out() -> None:
    early = answer("pass", evidence=[], absence=True, absence_turns={"first": 1, "last": 2})
    model = Scripted(early, answer("fail", evidence=[{"turn": 5, "quote": "five five five"}]))

    found = await criterion(model, text="Never reads the phone number back.")

    assert (found.outcome, found.re_asks) == (Outcome.FAIL, 1)
    assert "Check turns 3 to 5 too" in model.requests[1]


async def test_an_empty_quote_or_a_misshapen_answer_is_invalid_evidence_not_a_crash() -> None:
    empty = answer("fail", evidence=[{"turn": 3, "quote": " "}])
    misshapen = {"verdict": "pass"}

    first = await criterion(Scripted(empty, empty))
    second = await criterion(Scripted(misshapen, misshapen))

    assert (first.outcome, first.error_reason) == (Outcome.ERROR, "invalid_evidence")
    assert (second.outcome, second.error_reason) == (Outcome.ERROR, "invalid_evidence")


def test_a_group_of_errors_is_described_by_the_errors_in_it() -> None:
    group = ExceptionGroup("unhandled errors in a TaskGroup", [JudgeUnavailable("HTTP 429")])

    assert describe_exception(group) == "JudgeUnavailable: HTTP 429"
