import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from tests.conftest import (
    Db,
    claim,
    create_agent_id,
    create_scenario,
    eventually,
    finish,
    make_evaluator,
    save_settings,
    start_run,
)
from yaksh.config import Settings
from yaksh.db.models import (
    Conversation,
    Evaluation,
    EvaluationItem,
    JudgeCall,
    JudgeVersion,
    MetricValue,
)
from yaksh.domain.answering import AnsweredBy
from yaksh.domain.conversations import (
    CallOutcome,
    EndReason,
    Role,
    Transcript,
    Turn,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.evaluations import DecidedBy, EvaluationState, MetricKey, Outcome, Verdict
from yaksh.domain.language_models import ModelAnswer, ModelCallError
from yaksh.evaluation import judging
from yaksh.evaluation.evaluations import MAX_ATTEMPTS

TURNS = [
    Turn(role=Role.AGENT, text="Thanks for calling, this is Ava.", started_at_ms=0, ended_at_ms=1),
    Turn(role=Role.CALLER, text="Can I move my cleaning?", started_at_ms=2, ended_at_ms=3),
    Turn(
        role=Role.AGENT,
        text="Sure, it is now next Thursday at four p.m.",
        started_at_ms=4,
        ended_at_ms=5,
    ),
]
CALL = Transcript(turns=TURNS, wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)])
RULES = [
    {
        "kind": "llm",
        "key": "no-promises",
        "name": "Makes no promises it cannot keep",
        "applies_when": "the agent moves an appointment",
        "pass_when": "the agent states the new time",
        "fail_when": "the agent promises a time without checking",
        "role": "deciding",
    },
    {"kind": "phrase", "key": "greets", "name": "Greets as Ava", "expects": "required",
     "value": "this is Ava", "where": "first_agent_turn"},
]  # fmt: skip


class Judge:
    """Passes every criterion and fails every agent rule, quoting turn 3."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> ModelAnswer:
        self.asked.append(name)
        if name == "instructions":
            followed = {
                "call_quote": None,
                "record_quote": None,
                "instruction_quote": None,
                "reasoning": "...",
                "verdict": "pass",
            }
            broken = followed | {
                "call_quote": {"turn": 3, "quote": "next Thursday at four p.m."},
                "instruction_quote": "Read the new time back",
                "verdict": "fail",
            }
            data = {"objective": followed, "procedure": broken, "boundary": followed}
            return ModelAnswer(data=data, model="judge-1", input_tokens=900, output_tokens=60)
        if name == "caller_check":
            data = {"findings": [], "impact": [], "blame_risk": "none"}
            return ModelAnswer(data=data, model="judge-1", input_tokens=900, output_tokens=60)
        if name == "hallucination":
            contradiction = {
                "call_quote": {"turn": 3, "quote": "four p.m."},
                "record_quote": None,
                "document": "hours.md",
                "document_quote": "Thursday: 8 am to 5 pm.",
                "reasoning": "...",
            }
            data = {"contradictions": [contradiction], "reasoning": "...", "verdict": "fail"}
            return ModelAnswer(data=data, model="judge-1", input_tokens=900, output_tokens=60)
        data = {
            "evidence": [{"turn": 3, "quote": "next Thursday at 4 pm"}],
            "record_evidence": [],
            "absence": False,
            "absence_turns": None,
            "reasoning": "Turn 3 states the new time.",
            "verdict": "pass" if name == "criterion" else "fail",
            "kind": None,
        }
        if name == "agent_rule":
            data = {"applies": True} | data
        return ModelAnswer(data=data, model="judge-1", input_tokens=900, output_tokens=60)

    async def close(self) -> None:
        pass


async def test_a_completed_call_is_judged_and_a_stopped_one_gets_only_code_checks(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    hours = await client.post(
        "/api/v1/documents", json={"name": "hours", "text": "Thursday: 8 am to 5 pm."}
    )
    agent = await create_agent_id(
        client,
        name="Clinic",
        rules=RULES,
        config="Read the new time back before you end the call.",
        knowledge_base=[{"document_id": hours.json()["id"], "name": "hours.md"}],
    )
    scenario = await create_scenario(client, agent, criteria=["The agent reads the new time back."])
    run = await start_run(client, agent, [scenario["id"]], repeats=2)
    assert run.status_code == 202, run.text
    completed, stopped = str(await claim(db)), str(await claim(db))
    await finish(
        db,
        completed,
        CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP),
        transcript=CALL,
    )
    await finish(
        db, stopped, CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST), transcript=CALL
    )
    judge = Judge()
    stop = asyncio.Event()
    await save_settings(db, {"audit": {"sample_rate": 1.0}})
    evaluator = asyncio.create_task(make_evaluator(db, settings, judge).run(stop))

    async def evaluations() -> list[Evaluation]:
        async with db() as session:
            return list(await session.scalars(select(Evaluation)))

    try:
        done = await eventually(
            evaluations, lambda found: all(e.state is EvaluationState.DONE for e in found)
        )
    finally:
        stop.set()
        await evaluator

    by_call = {str(e.conversation_id): e for e in done}
    async with db() as session:
        items = {
            (str(item.evaluation_id), item.item_key): item
            for item in await session.scalars(select(EvaluationItem).order_by(EvaluationItem.id))
        }
        calls = list(await session.scalars(select(JudgeCall)))
        versions = {v.judge: v for v in await session.scalars(select(JudgeVersion))}
    judged, plain = by_call[completed], by_call[stopped]
    assert (judged.scenario_verdict, judged.conversation_verdict) == (Verdict.PASS, Verdict.FAIL)
    assert (judged.effective_scenario_verdict, plain.scenario_verdict) == (Verdict.PASS, None)
    assert (judged.audit, plain.audit) == (True, False)
    assert [key for (evaluation, key) in items if evaluation == str(judged.id)] == [
        "criterion-1",
        "rule-no-promises",
        "rule-greets",
        "instructions",
        "hallucination",
        "caller_check",
    ]
    assert {key for (evaluation, key) in items if evaluation == str(plain.id)} == set()
    criterion = items[str(judged.id), "criterion-1"]
    assert (criterion.machine_outcome, criterion.decided_by, criterion.subject) == (
        Outcome.PASS,
        DecidedBy.LLM,
        "The agent reads the new time back.",
    )
    assert criterion.judge_version_id == versions["criterion"].id
    assert items[str(judged.id), "rule-greets"].decided_by is DecidedBy.CODE
    assert sorted(judge.asked) == [
        "agent_rule",
        "caller_check",
        "criterion",
        "hallucination",
        "instructions",
    ]
    assert {(call.input_tokens, call.model_returned) for call in calls} == {(900, "judge-1")}
    assert len(calls) == 5
    stored_rules = (await client.get(f"/api/v1/agents/{agent}")).json()["rules"]
    assert [rule["key"] for rule in stored_rules] == ["no-promises", "greets"]
    shown = (await client.get(f"/api/v1/conversations/{completed}/evaluation")).json()
    assert (shown["scenario_verdict"], shown["effective_conversation_verdict"]) == ("pass", "fail")
    assert {item["item_key"]: item["machine_outcome"] for item in shown["items"]} == {
        "criterion-1": "pass",
        "rule-no-promises": "fail",
        "rule-greets": "pass",
        "instructions": "fail",
        "hallucination": "fail",
        "caller_check": "pass",
    }


async def test_rule_results_count_only_the_calls_that_ran_the_rule_as_written(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    agent = await create_agent_id(client, name="Clinic", rules=RULES)
    scenario = await create_scenario(client, agent, criteria=["The agent reads the new time back."])

    async def judge_calls(repeats: int, judge: Judge | None) -> tuple[str, list[str]]:
        run = (await start_run(client, agent, [scenario["id"]], repeats=repeats)).json()
        ids = [str(await claim(db)) for _ in range(repeats)]
        for conversation in ids:
            outcome = CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
            await finish(db, conversation, outcome, transcript=CALL)
        stop = asyncio.Event()
        evaluator = asyncio.create_task(make_evaluator(db, settings, judge).run(stop))

        async def states() -> list[EvaluationState]:
            async with db() as session:
                return list(await session.scalars(select(Evaluation.state)))

        try:
            await eventually(states, lambda found: all(s is EvaluationState.DONE for s in found))
        finally:
            stop.set()
            await evaluator
        return run["id"], ids

    first_run, _ = await judge_calls(2, Judge())
    edited = [
        RULES[0] | {"name": "Promises nothing it cannot keep"},
        RULES[1] | {"name": "Greets the caller as Ava", "role": "deciding"},
    ]
    assert (
        await client.patch(f"/api/v1/agents/{agent}", json={"rules": edited})
    ).status_code == 200
    _, later = await judge_calls(2, Judge())
    await judge_calls(1, None)

    results = (await client.get(f"/api/v1/agents/{agent}/rule-results")).json()
    verdicts = (await client.get(f"/api/v1/runs/{first_run}/metrics")).json()["verdicts"]

    assert [(r["key"], r["counts"]) for r in results] == [
        ("no-promises", {"fail": 2}),
        ("greets", {"pass": 4}),
    ]
    assert [f["conversation_id"] for f in results[0]["failures"]] == later[::-1]
    assert results[1]["failures"] == []
    assert [(r["name"], r["role"], r["counts"]) for r in verdicts["rules"]] == [
        ("Greets as Ava", "reporting", {"pass": 2}),
        ("Makes no promises it cannot keep", "deciding", {"fail": 2}),
    ]
    missing = await client.get("/api/v1/agents/01a10000-0000-7000-8000-000000000000/rule-results")
    assert missing.status_code == 404


class Busy:
    """Rate limited on every judge call."""

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> ModelAnswer:
        raise ModelCallError("the model call failed: HTTP 429", temporary=True)

    async def close(self) -> None:
        pass


async def test_a_busy_judge_puts_the_evaluation_off_and_its_last_attempt_keeps_the_metrics(
    client: AsyncClient, db: Db, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(judging, "WAITS_S", (0.0,))
    agent = await create_agent_id(client, name="Clinic")
    scenario = await create_scenario(client, agent, criteria=["Reads the time back."])
    assert (await start_run(client, agent, [scenario["id"]])).status_code == 202
    conversation = str(await claim(db))
    await finish(
        db,
        conversation,
        CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP),
        transcript=CALL,
    )

    async def evaluate_once() -> Evaluation:
        stop = asyncio.Event()
        evaluator = asyncio.create_task(make_evaluator(db, settings, Busy()).run(stop))

        async def found() -> Evaluation:
            async with db() as session:
                return await session.scalar(select(Evaluation)) or Evaluation()

        try:
            return await eventually(
                found,
                lambda e: (
                    e.state is EvaluationState.DONE
                    or (e.failure is not None and e.state is EvaluationState.QUEUED)
                ),
            )
        finally:
            stop.set()
            await evaluator

    first = await evaluate_once()
    async with db.begin() as session:
        await session.execute(
            update(Evaluation).values(
                attempts=MAX_ATTEMPTS - 1, not_before=func.now(), failure=None
            )
        )
    last = await evaluate_once()

    assert (first.state, first.attempts, "HTTP 429" in (first.failure or "")) == (
        EvaluationState.QUEUED,
        1,
        True,
    )
    assert (last.state, last.scenario_verdict) == (EvaluationState.DONE, Verdict.NOT_SCORED)
    async with db() as session:
        items = list(await session.scalars(select(EvaluationItem)))
        metric_keys = set(await session.scalars(select(MetricValue.metric_key)))
    assert {(item.item_key, item.machine_outcome, item.error_reason) for item in items} == {
        ("criterion-1", Outcome.ERROR, "judge_unavailable"),
        ("caller_check", Outcome.ERROR, "judge_unavailable"),
    }
    assert MetricKey.USAGE in metric_keys


async def test_a_call_that_the_voicemail_answered_is_judged_only_by_the_rules_that_check_it(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    callback = {
        "kind": "llm",
        "key": "callback",
        "name": "Leaves a call-back number",
        "applies_when": "the agent leaves a message",
        "pass_when": "the message gives a number",
        "fail_when": "the message gives no number",
        "role": "deciding",
        "answered_by": "voicemail",
    }
    brand = {"kind": "phrase", "key": "brand", "name": "Names itself", "expects": "required",
             "value": "this is Ava", "answered_by": "any"}  # fmt: skip
    agent = await create_agent_id(client, name="Clinic", rules=[*RULES, callback, brand])
    scenario = await create_scenario(client, agent, criteria=["The agent reads the new time back."])
    run = (await start_run(client, agent, [scenario["id"]], repeats=2)).json()
    person, voicemail = str(await claim(db)), str(await claim(db))
    async with db.begin() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(voicemail))
            .values(answered_by=AnsweredBy.VOICEMAIL)
        )
    for conversation in (person, voicemail):
        ended = CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
        await finish(db, conversation, ended, transcript=CALL)
    stop = asyncio.Event()
    evaluator = asyncio.create_task(make_evaluator(db, settings, Judge()).run(stop))

    async def evaluations() -> list[Evaluation]:
        async with db() as session:
            return list(await session.scalars(select(Evaluation)))

    try:
        done = await eventually(
            evaluations, lambda found: all(e.state is EvaluationState.DONE for e in found)
        )
    finally:
        stop.set()
        await evaluator
    by_call = {str(e.conversation_id): e for e in done}
    async with db() as session:
        keys = [
            (str(item.evaluation_id), item.item_key)
            for item in await session.scalars(select(EvaluationItem).order_by(EvaluationItem.id))
        ]
    verdicts = (await client.get(f"/api/v1/runs/{run['id']}/metrics")).json()["verdicts"]

    def items_of(conversation: str) -> list[str]:
        return [key for evaluation, key in keys if evaluation == str(by_call[conversation].id)]

    assert items_of(voicemail) == ["rule-callback", "rule-brand"]
    assert items_of(person) == [
        "criterion-1",
        "rule-no-promises",
        "rule-greets",
        "rule-brand",
        "caller_check",
    ]
    machine = by_call[voicemail]
    assert (machine.scenario_verdict, machine.conversation_verdict) == (
        Verdict.NOT_SCORED,
        Verdict.FAIL,
    )
    assert [call["conversation_id"] for s in verdicts["scenarios"] for call in s["calls"]] == [
        person
    ]
    assert [
        (call["conversation_id"], call["answered_by"], call["verdict"])
        for call in verdicts["unplayed"]
    ] == [(voicemail, "voicemail", "fail")]
    assert (verdicts["pending"], verdicts["not_judged"], verdicts["coverage"]) == (0, 0, 1.0)
    assert {rule["key"]: rule["counts"] for rule in verdicts["rules"]}["callback"] == {"fail": 1}
