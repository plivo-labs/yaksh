import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update

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
from yaksh.db.models import AgentRecordRow, Conversation, Evaluation, EvaluationItem
from yaksh.domain.agent_records import (
    AgentRecord,
    CallRef,
    Found,
    Lookup,
    Pending,
    RecordState,
    RecordTool,
    RecordTurn,
    SavedValue,
)
from yaksh.domain.conversations import (
    CallOutcome,
    EndReason,
    Provenance,
    Role,
    Transcript,
    Turn,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.evaluations import EvaluationState, ItemRole, Outcome, Verdict
from yaksh.domain.language_models import ModelAnswer
from yaksh.domain.record_sources import RecordProvider, RecordSource
from yaksh.evaluation.agent_records import paired_turn
from yaksh.evaluation.record_checks import saved_data_problems
from yaksh.timings import Timings

TURNS = [
    Turn(
        role=Role.AGENT, text="Thanks for calling, this is Ava.", started_at_ms=0, ended_at_ms=900
    ),
    Turn(role=Role.CALLER, text="Can I move my cleaning?", started_at_ms=1000, ended_at_ms=1900),
    Turn(
        role=Role.AGENT,
        text="Sure, it is now next Thursday at four p.m.",
        started_at_ms=2000,
        ended_at_ms=2900,
    ),
]
CALL = Transcript(turns=TURNS, wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)])
SOURCE = {
    "provider": "plivo_cx",
    "url": "https://api.plivo.com/v1/Account/MAXXXX/AgentFlow/c2a36ee8-4f8b-4d56-8b5f-0173ef11ff8a/",
    "headers": [{"name": "Authorization", "value": "{{secrets.CX_AUTH}}"}],
}
YAKSH_NUMBER = "+15550100000"
"""The number the worker leased for the call."""
CLOCK_LAG = timedelta(seconds=7)
"""How long after the claim the call's clock starts: the worker prepares the call first."""
FAST = Timings(evaluator_poll_s=0.05, record_poll_s=0.05, record_wait_s=30)


class Reader:
    """Gives the scripted answers in turn, the last one again and again, and keeps each ask."""

    def __init__(self, *answers: Lookup) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[dict[str, str], CallRef]] = []

    async def find(self, source: RecordSource, headers: Mapping[str, str], call: CallRef) -> Lookup:
        self.asked.append((dict(headers), call))
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Judge:
    """Passes the criterion from the record, finds a saved value that does not match, and finds
    that the agent heard the caller right."""

    def __init__(self, *, from_record: bool = True) -> None:
        self.views: dict[str, str] = {}
        self.from_record = from_record

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> ModelAnswer:
        self.views[name] = user
        answers: dict[str, dict[str, Any]] = {
            "criterion": {
                "evidence": [] if self.from_record else [{"turn": 3, "quote": "next Thursday"}],
                "record_evidence": [{"line": 2, "quote": "move_booking"}]
                if self.from_record
                else [],
                "absence": False,
                "absence_turns": None,
                "reasoning": "The record shows the booking moved.",
                "verdict": "pass",
                "kind": None,
            },
            "caller_check": {"findings": [], "impact": [], "blame_risk": "none"},
            "saved_data": {
                "values": [
                    {
                        "name": "new_time",
                        "result": "contradicts",
                        "evidence": [{"turn": 3, "quote": "next Thursday at four p.m."}],
                        "reasoning": "The call settled Thursday; the agent saved Friday.",
                    }
                ],
                "reasoning": "One value does not match.",
            },
            "heard": {
                "values": [
                    {
                        "value": "Request",
                        "said": {"turn": 2, "quote": "move my cleaning"},
                        "heard": {"line": 1, "quote": "move my cleaning"},
                        "result": "same",
                        "reasoning": "Heard as said.",
                    }
                ],
                "reasoning": "...",
            },
        }
        return ModelAnswer(data=answers[name], model="judge-1", input_tokens=10, output_tokens=5)

    async def close(self) -> None:
        pass


async def saved_call(client: AsyncClient, db: Db) -> tuple[str, Conversation]:
    agent = await create_agent_id(client, record_source=SOURCE)
    scenario = await create_scenario(client, agent, criteria=["The agent moves the booking."])
    assert (await start_run(client, agent, [scenario["id"]])).status_code == 202
    conversation_id = str(await claim(db))
    async with db() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(caller_number=YAKSH_NUMBER)
        )
        await session.commit()
        claimed = await session.get_one(Conversation, conversation_id)
    assert claimed.started_at is not None
    outcome = CallOutcome(
        connected=True,
        end_reason=EndReason.AGENT_HANGUP,
        clock_started_at=claimed.started_at + CLOCK_LAG,
    )
    await finish(db, conversation_id, outcome, transcript=CALL)
    async with db() as session:
        return conversation_id, await session.get_one(Conversation, conversation_id)


def record_of(call: Conversation) -> AgentRecord:
    """The agent's record of the call, its lines at the times of Yaksh's turns."""
    assert call.clock_started_at is not None
    start = call.clock_started_at

    def at(ms: int) -> datetime:
        return start + timedelta(milliseconds=ms)

    return AgentRecord(
        provider=RecordProvider.PLIVO_CX,
        external_id="run-1",
        status="COMPLETED",
        complete=True,
        turns=[
            RecordTurn(role=Role.AGENT, text="Thanks for calling, this is Ava.", at=at(900)),
            RecordTurn(role=Role.CALLER, text="Can I move my cleaning?", at=at(2400)),
            RecordTurn(role=Role.CALLER, text="Thanks.", at=at(60_000)),
        ],
        saved=[SavedValue(name="new_time", value="Friday 4 pm")],
        tools=[RecordTool(name="move_booking", arguments='{"day": "Friday"}', at=at(2500))],
    )


async def evaluate(
    db: Db, settings: Settings, reader: Reader, judge: Judge, timings: Timings
) -> Evaluation:
    stop = asyncio.Event()
    readers = {RecordProvider.PLIVO_CX: reader}
    evaluator = make_evaluator(db, settings, judge, readers=readers, timings=timings)
    running = asyncio.create_task(evaluator.run(stop))

    async def evaluation() -> Evaluation:
        async with db() as session:
            return await session.scalar(select(Evaluation)) or Evaluation()

    try:
        return await eventually(evaluation, lambda found: found.state is EvaluationState.DONE)
    finally:
        stop.set()
        await running


async def test_a_record_still_being_written_waits_then_the_judges_read_it(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    await save_settings(db, secrets={"trigger:CX_AUTH": "Basic abc"})
    conversation_id, call = await saved_call(client, db)
    reader = Reader(Pending("the run is still running"), Found(record_of(call)))
    judge = Judge()

    done = await evaluate(db, settings, reader, judge, FAST)

    assert done.attempts == 1, "a wait for the record is not an attempt"
    assert len(reader.asked) == 2
    headers, ref = reader.asked[0]
    assert headers == {"Authorization": "Basic abc"}
    assert (ref.yaksh_number, ref.started_at) == (call.caller_number, call.started_at)
    assert (done.scenario_verdict, done.conversation_verdict) == (Verdict.PASS, Verdict.FAIL)
    async with db() as session:
        items = {item.item_key: item for item in await session.scalars(select(EvaluationItem))}
        row = await session.get_one(AgentRecordRow, call.id)
    assert (items["saved_data"].machine_outcome, items["saved_data"].role) == (
        Outcome.FAIL,
        ItemRole.DECIDING,
    )
    assert (items["heard"].machine_outcome, items["heard"].role) == (
        Outcome.PASS,
        ItemRole.REPORTING,
    )
    assert items["criterion-1"].machine_outcome is Outcome.PASS
    assert (row.state, row.external_id) == (RecordState.FOUND, "run-1")
    view = judge.views["criterion"]
    assert "[R1] Saved: new_time = Friday 4 pm" in view
    assert '[R2] Tool call: move_booking {"day": "Friday"}, no output reported' in view
    assert "[H1] Can I move my cleaning?" in judge.views["heard"]

    shown = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
    assert shown["agent_record"] == {"status": "found", "reason": None}
    record = (await client.get(f"/api/v1/conversations/{conversation_id}/agent-record")).json()
    assert [(turn["turn"], turn["at_ms"]) for turn in record["turns"]] == [
        (1, 900),
        (2, 2400),
        (None, 60_000),
    ], "a line pairs with the turn of its speaker that holds its time, or with none"
    assert [tool["at_ms"] for tool in record["tools"]] == [2500]
    assert (record["provider_label"], record["saved"]) == (
        "Plivo CX",
        [{"name": "new_time", "value": "Friday 4 pm"}],
    )


async def test_with_no_record_by_the_end_of_the_wait_the_call_is_judged_without_one(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    await save_settings(db, secrets={"trigger:CX_AUTH": "Basic abc"})
    conversation_id, call = await saved_call(client, db)
    reader = Reader(Pending("no run of this agent came from the number"))
    judge = Judge(from_record=False)

    done = await evaluate(db, settings, reader, judge, replace(FAST, record_wait_s=0.3))

    async with db() as session:
        keys = set(await session.scalars(select(EvaluationItem.item_key)))
        row = await session.get_one(AgentRecordRow, call.id)
    assert (row.state, row.reason) == (
        RecordState.MISSING,
        "no run of this agent came from the number",
    )
    assert keys == {"criterion-1", "caller_check"}, "no record, so no record checks"
    assert "Yaksh could not read the agent's own record of this call." in judge.views["criterion"]
    assert done.scenario_verdict is Verdict.PASS
    shown = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
    assert shown["agent_record"]["status"] == "missing"


async def test_a_secret_that_is_not_set_is_no_record_without_asking_the_provider(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    _, call = await saved_call(client, db)
    reader = Reader(Pending("never asked"))

    await evaluate(db, settings, reader, Judge(from_record=False), FAST)

    async with db() as session:
        row = await session.get_one(AgentRecordRow, call.id)
    assert reader.asked == []
    assert row.state is RecordState.MISSING
    assert row.reason is not None and "CX_AUTH" in row.reason


def test_a_record_line_pairs_with_the_turn_that_holds_its_time() -> None:
    turns = [
        Turn(role=Role.CALLER, text="Hi.", started_at_ms=1000, ended_at_ms=2000),
        Turn(role=Role.CALLER, text="Friday.", started_at_ms=3500, ended_at_ms=4000),
    ]
    line = RecordTurn(role=Role.CALLER, text="Friday.", at=None)

    assert paired_turn(line, 3900, turns) == 2
    assert paired_turn(line, 9000, turns) is None


def test_a_turn_that_did_not_play_cannot_alone_show_a_saved_value_is_wrong() -> None:
    turns = [
        Turn(
            role=Role.CALLER,
            text="Thursday, please.",
            started_at_ms=0,
            ended_at_ms=900,
            provenance=Provenance.TRANSMITTED,
        ),
        Turn(
            role=Role.CALLER,
            text="Actually, Friday.",
            started_at_ms=1000,
            ended_at_ms=1900,
            provenance=Provenance.CUT,
        ),
    ]
    check = saved_data_problems(turns, ["day"])

    def contradicts(turn: int, quote: str) -> dict[str, Any]:
        evidence = [{"turn": turn, "quote": quote}]
        return {
            "values": [{"name": "day", "result": "contradicts", "evidence": evidence}],
            "reasoning": "",
        }

    unplayed, _ = check(contradicts(2, "Friday"))
    played, _ = check(contradicts(1, "Thursday"))

    assert len(unplayed) == 1 and "not_checkable" in unplayed[0]
    assert played == []
