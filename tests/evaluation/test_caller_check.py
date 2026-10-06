import asyncio
from dataclasses import replace
from typing import Any

from tests.conftest import Scripted
from yaksha.domain.conversations import EndReason, Role, Transcript, Turn, WireEvent, WireEventKind
from yaksha.domain.evaluations import DecidedBy, ItemRole, Outcome, UnsureKind
from yaksha.domain.languages import Language
from yaksha.evaluation.caller_check import applied, check_caller, facts
from yaksha.evaluation.judging import ItemResult


def turn(role: Role, text: str, at_ms: int) -> Turn:
    return Turn(role=role, text=text, started_at_ms=at_ms, ended_at_ms=at_ms + 1_000)


def criterion(number: int, outcome: Outcome = Outcome.FAIL) -> ItemResult:
    return ItemResult(
        key=f"criterion-{number}",
        subject=f"Criterion {number}",
        judge="criterion",
        decided_by=DecidedBy.LLM,
        role=ItemRole.DECIDING,
        outcome=outcome,
        unsure_kind=UnsureKind.UNCLEAR if outcome is Outcome.UNSURE else None,
    )


def check(blame: str, *impact: tuple[int, str]) -> ItemResult:
    answer: dict[str, Any] = {
        "findings": [{"turn": 2, "finding": "The caller gave the wrong date of birth."}],
        "impact": [
            {"criterion": number, "owner": owner, "effect": "..."} for number, owner in impact
        ],
        "blame_risk": blame,
    }
    return ItemResult(
        key="caller_check",
        subject="Yaksha's caller kept to its test",
        judge="caller_check",
        decided_by=DecidedBy.LLM,
        role=ItemRole.REPORTING,
        outcome=Outcome.PASS,
        answer=answer,
    )


def test_code_finds_how_the_caller_ended_the_call() -> None:
    waited = Transcript(
        turns=[
            turn(Role.CALLER, "Can I move my visit?", 0),
            turn(Role.AGENT, "Sure, let me check that for you.", 2_000),
        ],
        wire_events=[WireEvent(kind=WireEventKind.END_CALL, at_ms=6_000, detail="done")],
    )
    last_word = Transcript(
        turns=[turn(Role.AGENT, "Goodbye!", 0), turn(Role.CALLER, "Bye.", 2_000)]
    )

    assert facts(waited, EndReason.CALLER_HANGUP, Language.EN) == [
        "The caller hung up, and the agent's last turn has no closing words.",
        "The caller hung up within 10 s of the agent saying it would check or asking it to wait.",
    ]
    assert facts(last_word, EndReason.TURN_LIMIT, Language.EN) == [
        "The last turn, 2, is the caller's.",
        "The test's turn limit ended the call.",
    ]
    assert facts(last_word, EndReason.AGENT_HANGUP, Language.EN) == [
        "The last turn, 2, is the caller's."
    ]


def test_likely_blame_blocks_only_the_criteria_it_changed() -> None:
    found = applied(
        [criterion(1), criterion(2)], check("likely", (2, "caller")), EndReason.AGENT_HANGUP
    )

    assert [item.outcome for item in found] == [Outcome.FAIL, Outcome.BLOCKED]
    assert found[1].caller_effect == {"owner": "caller", "effect": "...", "blame": "likely"}
    assert found[0].caller_effect is None


def test_possible_blame_keeps_the_verdict_and_marks_it() -> None:
    [found] = applied([criterion(1, Outcome.UNSURE)], check("possible", (1, "caller")), None)

    assert found.caller_effect is not None
    assert (found.outcome, found.unsure_kind, found.caller_effect["blame"]) == (
        Outcome.UNSURE,
        UnsureKind.UNCLEAR,
        "possible",
    )


def test_a_criterion_the_test_limit_cut_off_is_blocked_whatever_the_blame() -> None:
    cut = check("none", (2, "test_settings"))

    limited = applied([criterion(1), criterion(2)], cut, EndReason.TURN_LIMIT)
    unlimited = applied([criterion(1), criterion(2)], cut, EndReason.AGENT_HANGUP)

    assert [item.outcome for item in limited] == [Outcome.FAIL, Outcome.BLOCKED]
    assert [item.outcome for item in unlimited] == [Outcome.FAIL, Outcome.FAIL]


async def test_the_check_reads_the_caller_side_and_names_criteria_that_exist() -> None:
    wrong = {
        "findings": [],
        "impact": [{"criterion": 7, "owner": "caller", "effect": "x"}],
        "blame_risk": "possible",
    }
    clean = {"findings": [], "impact": [], "blame_risk": "none"}
    model = Scripted(wrong, clean)
    transcript = Transcript(turns=[turn(Role.AGENT, "Hello.", 0), turn(Role.CALLER, "Hi.", 2_000)])

    found = await check_caller(
        model,
        "VIEW",
        transcript,
        "You are Jordan Lee, born 14 March 1990.",
        ["Asks for the date of birth.", "Reads it back."],
        EndReason.AGENT_HANGUP,
        Language.EN,
        slots=asyncio.Semaphore(1),
        retry_later=True,
    )

    assert (found.key, found.outcome, found.re_asks, found.role) == (
        "caller_check",
        Outcome.PASS,
        1,
        ItemRole.REPORTING,
    )
    assert "CALLER INSTRUCTIONS\nYou are Jordan Lee" in model.requests[0]
    assert "1. Asks for the date of birth.\n2. Reads it back." in model.requests[0]
    assert "Criterion 7 does not exist (1 to 2)." in model.requests[1]


def test_a_call_in_another_language_gets_no_phrase_facts() -> None:
    hindi = Transcript(turns=[turn(Role.AGENT, "ठीक है, धन्यवाद। अलविदा!", 0)])

    assert facts(hindi, EndReason.CALLER_HANGUP, Language.HINGLISH) == []


def test_a_failed_check_blocks_nothing_except_unmet_criteria_on_a_limit_call() -> None:
    failed = replace(check("likely", (1, "caller")), outcome=Outcome.ERROR)
    criteria = [criterion(1), criterion(2, Outcome.PASS)]

    plain = applied(criteria, failed, EndReason.AGENT_HANGUP)
    limited = applied(criteria, failed, EndReason.DURATION_LIMIT)

    assert [item.outcome for item in plain] == [Outcome.FAIL, Outcome.PASS]
    assert [item.outcome for item in limited] == [Outcome.BLOCKED, Outcome.PASS]


def test_any_qualifying_impact_blocks_and_a_pass_is_never_blocked() -> None:
    both = check("none", (1, "caller"), (1, "test_settings"))
    likely = check("likely", (1, "caller"), (2, "caller"))
    hidden = replace(criterion(2), outcome=Outcome.UNSURE, unsure_kind=UnsureKind.HIDDEN_ACTION)

    [cut] = applied([criterion(1)], both, EndReason.TURN_LIMIT)
    kept = applied([criterion(1, Outcome.PASS), hidden], likely, EndReason.AGENT_HANGUP)

    assert cut.outcome is Outcome.BLOCKED
    assert [item.outcome for item in kept] == [Outcome.PASS, Outcome.UNSURE]
    assert kept[0].caller_effect is not None
