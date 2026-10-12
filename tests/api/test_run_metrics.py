import uuid

from httpx import AsyncClient
from sqlalchemy import update

from tests.conftest import (
    Db,
    claim,
    create_agent_id,
    create_persona,
    create_scenario,
    evaluate_queued,
    finish,
    start_run,
)
from yaksh.db.models import Evaluation as EvaluationRow
from yaksh.domain.conversations import (
    CallOutcome,
    EndReason,
    Transcript,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.evaluations import (
    DecidedBy,
    EvaluationState,
    ItemRole,
    Metric,
    MetricKey,
    Outcome,
    Share,
    Verdict,
)
from yaksh.domain.latency import Latency, Reply
from yaksh.evaluation import evaluations
from yaksh.evaluation.criteria import AGENT_RULE, CRITERION
from yaksh.evaluation.evaluations import MAX_ATTEMPTS, Evaluated
from yaksh.evaluation.judging import ItemResult

CONNECTED = Transcript(wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=500)])


def taking(expected: int, unanswered: int, talked_over: int, *flags: str) -> Metric:
    counts = {"expected": expected, "unanswered": unanswered, "talked_over": talked_over}
    return Metric(value={"waits": [], **counts}, flags=list(flags))


def responses(*pairs: tuple[int, int]) -> Metric:
    replies = [Reply(start_ms=start, speech_ms=speech) for start, speech in pairs]
    return Metric(value=Latency.of(replies).model_dump(mode="json"))


def share(count: int, total: int) -> dict[str, object]:
    return Share.of(count, total).model_dump()


async def test_run_numbers_pool_the_counted_calls_overall_and_by_category(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client, name="Clinic")
    usual = await create_scenario(client, agent, name="Usual", category="happy_path")
    edge = await create_scenario(client, agent, name="Edge", category="edge_case")
    response = await start_run(client, agent, [usual["id"], edge["id"]], repeats=2)
    run = response.json()
    ids = [await claim(db) for _ in range(4)]
    assert None not in ids
    first, second, third, fourth = [str(i) for i in ids]
    connected = CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP, stream_opened_ms=500)
    await finish(db, first, connected, transcript=CONNECTED)
    await finish(db, second, connected, transcript=CONNECTED)
    # stopped by the user after it connected: not counted
    stopped = connected.model_copy(update={"end_reason": EndReason.USER_REQUEST})
    await finish(db, fourth, stopped, transcript=CONNECTED)
    await evaluate_queued(
        db,
        {
            first: {
                MetricKey.TURN_TAKING: taking(3, 1, 0, "unanswered"),
                MetricKey.RESPONSE_TIME: responses((1_000, 1_600), (5_000, 6_000)),
            },
            second: {
                MetricKey.TURN_TAKING: taking(2, 0, 1, "long_wait"),
                MetricKey.RESPONSE_TIME: responses((2_000, 4_500)),
                MetricKey.AGENT_REPETITION: Metric(value={"runs": []}, flags=["repetition"]),
            },
        },
    )
    # not evaluated yet
    await finish(db, third, CallOutcome(connected=False, end_reason=EndReason.NO_ANSWER))

    found = (await client.get(f"/api/v1/runs/{run['id']}/metrics")).json()

    assert found["overall"] == {
        "conversations": 3,
        "evaluated": 2,
        "pending": 1,
        "failed": 0,
        "connected": share(2, 3),
        "errors_before_connect": 0,
        "response_p50_ms": 1_000,
        "response_p90_ms": 2_500,
        "unanswered": share(1, 2),
        "talked_over": share(1, 2),
        "long_wait": share(1, 2),
        "dead_air": share(0, 2),
        "flags": {"long_wait": 1, "repetition": 1, "unanswered": 1},
    }
    assert share(2, 3) == {"count": 2, "total": 3, "low": 0.208, "high": 0.939}
    assert [
        (group["category"], group["numbers"]["conversations"]) for group in found["by_category"]
    ] == [("happy_path", 2), ("edge_case", 1)]
    assert found["by_category"][0]["numbers"]["connected"] == share(1, 2)
    assert found["by_surroundings"] == [
        {"surroundings": {"sounds": [], "auto": None, "speaker": None}, "numbers": found["overall"]}
    ]
    run_read = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert (run_read["response_p50_ms"], run_read["response_p90_ms"]) == (1_000, 2_500)


async def test_run_numbers_count_what_each_call_got_to(client: AsyncClient, db: Db) -> None:
    agent = await create_agent_id(client, name="Shop")
    quiet = await create_scenario(client, agent, name="Quiet")
    street = await create_persona(
        client, name="Street caller", surroundings={"sounds": [{"sound": "street", "db": -5}]}
    )
    loud = await create_scenario(client, agent, name="Loud", persona_id=street["id"])
    run = (
        await start_run(client, agent, [quiet["id"], loud["id"]], repeats=2, max_retries=0)
    ).json()
    ids = [await claim(db) for _ in range(4)]
    assert None not in ids
    # The fourth conversation stays on the line.
    crashed, stopped, failed, _ = [str(i) for i in ids]
    # The worker failed after the call connected: the record has the connected event, but no
    # stream opening.
    await finish(
        db,
        crashed,
        CallOutcome(connected=True, end_reason=EndReason.ERROR, caller_error="worker failed"),
        transcript=CONNECTED,
    )
    await finish(
        db,
        stopped,
        CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST, stream_opened_ms=500),
        transcript=CONNECTED,
    )
    await finish(db, failed, CallOutcome(connected=False, end_reason=EndReason.NO_ANSWER))
    async with db() as session:
        while (evaluation := await evaluations.claim(session, "e1", 60)) is not None:
            if str(evaluation.conversation_id) == failed:
                await evaluations.fail(
                    session, evaluation.id, evaluation.claim_seq, MAX_ATTEMPTS, "boom"
                )
            else:
                answer = 9_000 if str(evaluation.conversation_id) == crashed else 20_000
                metrics = {MetricKey.RESPONSE_TIME: responses((1_000, answer))}
                await evaluations.finish(
                    session,
                    evaluation.id,
                    evaluation.claim_seq,
                    Evaluated(metrics=metrics),
                    audit=False,
                )

    found = (await client.get(f"/api/v1/runs/{run['id']}/metrics")).json()

    overall = found["overall"]
    assert {key: overall[key] for key in ("conversations", "evaluated", "pending", "failed")} == {
        "conversations": 3,
        "evaluated": 1,
        "pending": 1,
        "failed": 1,
    }
    assert (overall["connected"], overall["errors_before_connect"]) == (share(1, 2), 0)
    assert [
        ([s["sound"] for s in group["surroundings"]["sounds"]], group["numbers"]["conversations"])
        for group in found["by_surroundings"]
    ] == [
        ([], 2),
        (["street"], 1),
    ]
    # The call stopped by the user is not counted, so its slow response is not either.
    run_read = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert (overall["response_p90_ms"], run_read["response_p90_ms"]) == (8_000, 8_000)


async def test_run_verdicts_pool_judged_calls_by_scenario(client: AsyncClient, db: Db) -> None:
    agent = await create_agent_id(client, name="Shop")
    usual = await create_scenario(client, agent, name="Usual", criteria=["Greets."])
    edge = await create_scenario(client, agent, name="Edge", criteria=["Refuses."])
    run = (
        await start_run(client, agent, [usual["id"], edge["id"]], repeats=2, max_retries=0)
    ).json()
    ids = [str(await claim(db)) for _ in range(4)]
    for conversation in ids:
        await finish(
            db, conversation, CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
        )
    async with db() as session:
        versions = await evaluations.stored_judge_versions(
            session,
            [
                CRITERION.version("openai_compatible", "judge-1", {}),
                AGENT_RULE.version("openai_compatible", "judge-1", {}),
            ],
        )
    # Claims follow the run's order: usual, edge, usual, edge.
    outcomes = {
        ids[0]: Outcome.PASS,
        ids[1]: Outcome.FAIL,
        ids[2]: Outcome.PASS,
        ids[3]: Outcome.FAIL,
    }
    async with db() as session:
        while (evaluation := await evaluations.claim(session, "e1", 60)) is not None:
            outcome = outcomes[str(evaluation.conversation_id)]
            items = [
                ItemResult(
                    key="criterion-1",
                    subject="Greets."
                    if str(evaluation.conversation_id) in ids[::2]
                    else "Refuses.",
                    judge="criterion",
                    decided_by=DecidedBy.LLM,
                    role=ItemRole.DECIDING,
                    outcome=outcome,
                ),
                ItemResult(
                    key="caller_check",
                    subject="Yaksh's caller kept to its test",
                    judge=None,
                    decided_by=DecidedBy.LLM,
                    role=ItemRole.REPORTING,
                    outcome=Outcome.PASS,
                    answer={"findings": [], "impact": [], "blame_risk": "possible"},
                ),
                ItemResult(
                    key="rule-polite",
                    subject="Polite.",
                    judge="agent_rule",
                    decided_by=DecidedBy.LLM,
                    role=ItemRole.DECIDING,
                    outcome=Outcome.ERROR
                    if str(evaluation.conversation_id) == ids[0]
                    else Outcome.PASS,
                ),
            ]
            verdict = Verdict.PASS if outcome is Outcome.PASS else Verdict.FAIL
            await evaluations.finish(
                session,
                evaluation.id,
                evaluation.claim_seq,
                Evaluated(
                    metrics={},
                    items=items,
                    scenario_verdict=verdict,
                    conversation_verdict=verdict,
                    judge_versions=versions,
                ),
                audit=False,
            )
    # Make the edge scenario pass once, so it is the inconsistent one.
    async with db.begin() as session:
        await session.execute(
            update(EvaluationRow)
            .where(EvaluationRow.conversation_id == uuid.UUID(ids[3]))
            .values(effective_scenario_verdict=Verdict.PASS)
        )

    found = (await client.get(f"/api/v1/runs/{run['id']}/metrics")).json()["verdicts"]

    assert (found["pass_rate"], found["coverage"], found["pass_hat_2"]) == (0.75, 1.0, 0.5)
    assert (found["worst"], found["best"], found["interval_low"]) == (0.75, 0.75, None)
    assert (found["pending"], found["not_judged"]) == (0, 0)
    assert [
        (s["name"], [(c["repeat"], c["verdict"]) for c in s["calls"]]) for s in found["scenarios"]
    ] == [("Usual", [(1, "pass"), (2, "pass")]), ("Edge", [(1, "fail"), (2, "pass")])]
    assert found["inconsistent"] == [edge["id"]]
    assert [(c["text"], c["counts"], c["rate"]) for c in found["criteria"]] == [
        ("Greets.", {"pass": 2}, 1.0),
        ("Refuses.", {"fail": 2}, 0.0),
    ]
    assert (found["decided_by"], found["errors"]) == ({"llm": 7}, 1)
    assert [(c["calls"], c["possible"], c["likely"]) for c in found["callers"]] == [(2, 2, 0)] * 2
    assert [(v["judge"], v["items"]) for v in found["judge_versions"]] == [
        ("agent_rule", 4),
        ("criterion", 4),
    ]


async def test_run_verdicts_leave_out_calls_with_no_verdict_yet(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client, name="Shop")
    scenario = await create_scenario(client, agent, name="Usual", criteria=["Greets."])
    run = (await start_run(client, agent, [scenario["id"]], repeats=4, max_retries=0)).json()
    ids = [str(await claim(db)) for _ in range(4)]
    for conversation in ids:
        await finish(
            db, conversation, CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
        )
    errored_check = ItemResult(
        key="caller_check",
        subject="Yaksh's caller kept to its test",
        judge=None,
        decided_by=DecidedBy.LLM,
        role=ItemRole.REPORTING,
        outcome=Outcome.ERROR,
    )
    async with db() as session:
        judged = await evaluations.claim(session, "e1", 60)
        no_judge = await evaluations.claim(session, "e1", 60)
        assert judged is not None and no_judge is not None
        await evaluations.finish(
            session,
            judged.id,
            judged.claim_seq,
            Evaluated(
                metrics={},
                items=[errored_check],
                scenario_verdict=Verdict.PASS,
                conversation_verdict=Verdict.PASS,
            ),
            audit=False,
        )
        await evaluations.finish(
            session, no_judge.id, no_judge.claim_seq, Evaluated(metrics={}), audit=False
        )
        assert await evaluations.claim(session, "e1", 60) is not None
    async with db.begin() as session:
        await session.execute(
            update(EvaluationRow)
            .where(EvaluationRow.conversation_id == uuid.UUID(ids[3]))
            .values(state=EvaluationState.FAILED)
        )

    found = (await client.get(f"/api/v1/runs/{run['id']}/metrics")).json()["verdicts"]

    assert (found["pending"], found["not_judged"]) == (1, 1)
    assert [(c["repeat"], c["verdict"]) for c in found["scenarios"][0]["calls"]] == [
        (1, "pass"),
        (4, None),
    ]
    assert (found["pass_rate"], found["coverage"], found["worst"], found["best"]) == (
        1.0,
        0.5,
        0.5,
        1.0,
    )
    assert found["callers"] == []


async def test_repeats_compare_only_calls_with_the_same_persona(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client, name="Shop")
    calm = (await create_persona(client, name="Calm caller"))["id"]
    rushed = (await create_persona(client, name="Rushed caller"))["id"]
    scenario = await create_scenario(client, agent, name="Usual", criteria=["Greets."])
    run = (
        await start_run(
            client,
            agent,
            [{"scenario_id": scenario["id"], "persona_ids": [calm, rushed]}],
            repeats=2,
            max_retries=0,
        )
    ).json()
    # Claims follow the run's order: calm, rushed, calm, rushed.
    ids = [str(await claim(db)) for _ in range(4)]
    for conversation in ids:
        await finish(
            db, conversation, CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
        )
    async with db() as session:
        while (evaluation := await evaluations.claim(session, "e1", 60)) is not None:
            verdict = Verdict.PASS if str(evaluation.conversation_id) in ids[::2] else Verdict.FAIL
            await evaluations.finish(
                session,
                evaluation.id,
                evaluation.claim_seq,
                Evaluated(metrics={}, scenario_verdict=verdict, conversation_verdict=verdict),
                audit=False,
            )

    found = (await client.get(f"/api/v1/runs/{run['id']}/metrics")).json()["verdicts"]

    assert (found["pass_hat_2"], found["pass_hat_2_scenarios"]) == (0.5, 2)
    assert found["inconsistent"] == []
    assert [(c["repeat"], c["persona"], c["verdict"]) for c in found["scenarios"][0]["calls"]] == [
        (1, "Calm caller", "pass"),
        (1, "Rushed caller", "fail"),
        (2, "Calm caller", "pass"),
        (2, "Rushed caller", "fail"),
    ]


async def test_run_verdicts_compare_repeats_within_each_data_set(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client, name="Movers")
    scenario = await create_scenario(
        client,
        agent,
        name="Moves",
        criteria=["Confirms {{Moving to}}."],
        data_sets=[
            {"name": "Austin", "known_facts": [{"name": "Moving to", "value": "Austin"}]},
            {"name": "Denver", "known_facts": [{"name": "Moving to", "value": "Denver"}]},
        ],
    )
    run = (await start_run(client, agent, [scenario["id"]], repeats=2, max_retries=0)).json()
    ids = [str(await claim(db)) for _ in range(4)]
    for conversation in ids:
        await finish(
            db, conversation, CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
        )
    async with db() as session:
        versions = await evaluations.stored_judge_versions(
            session, [CRITERION.version("openai_compatible", "judge-1", {})]
        )
    # Claims follow the run's order: Austin, Denver, Austin, Denver. Austin always passes.
    austin = set(ids[::2])
    async with db() as session:
        while (evaluation := await evaluations.claim(session, "e1", 60)) is not None:
            passed = str(evaluation.conversation_id) in austin
            outcome = Outcome.PASS if passed else Outcome.FAIL
            verdict = Verdict.PASS if passed else Verdict.FAIL
            item = ItemResult(
                key="criterion-1",
                subject=f"Confirms {'Austin' if passed else 'Denver'}.",
                judge="criterion",
                decided_by=DecidedBy.LLM,
                role=ItemRole.DECIDING,
                outcome=outcome,
            )
            await evaluations.finish(
                session,
                evaluation.id,
                evaluation.claim_seq,
                Evaluated(
                    metrics={},
                    items=[item],
                    scenario_verdict=verdict,
                    conversation_verdict=verdict,
                    judge_versions=versions,
                ),
                audit=False,
            )

    found = (await client.get(f"/api/v1/runs/{run['id']}/metrics")).json()["verdicts"]

    assert (found["pass_rate"], found["pass_hat_2"], found["inconsistent"]) == (0.5, 0.5, [])
    assert [(c["text"], c["counts"]) for c in found["criteria"]] == [
        ("Confirms {{Moving to}}.", {"pass": 2, "fail": 2})
    ]
