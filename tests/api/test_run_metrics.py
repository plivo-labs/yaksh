from httpx import AsyncClient

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
from truman.domain.conversations import (
    CallOutcome,
    EndReason,
    Transcript,
    WireEvent,
    WireEventKind,
)
from truman.domain.evaluations import Metric, MetricKey, Share
from truman.domain.latency import Latency, Reply
from truman.evaluation import evaluations
from truman.evaluation.evaluations import MAX_ATTEMPTS, Evaluated

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
    edge = await create_scenario(client, agent, name="Edge", category="boundary")
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
    ] == [("happy_path", 2), ("boundary", 1)]
    assert found["by_category"][0]["numbers"]["connected"] == share(1, 2)
    assert found["by_noise"] == [
        {"noise": {"sound": "none", "level": "busy"}, "numbers": found["overall"]}
    ]
    run_read = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert (run_read["response_p50_ms"], run_read["response_p90_ms"]) == (1_000, 2_500)


async def test_run_numbers_count_what_each_call_got_to(client: AsyncClient, db: Db) -> None:
    agent = await create_agent_id(client, name="Shop")
    quiet = await create_scenario(client, agent, name="Quiet")
    street = await create_persona(
        client, name="Street caller", background_noise={"sound": "street", "level": "loud"}
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
                    session, evaluation.id, evaluation.claim_seq, Evaluated(metrics=metrics)
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
        (group["noise"]["sound"], group["numbers"]["conversations"]) for group in found["by_noise"]
    ] == [
        ("none", 2),
        ("street", 1),
    ]
    # The call stopped by the user is not counted, so its slow response is not either.
    run_read = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert (overall["response_p90_ms"], run_read["response_p90_ms"]) == (8_000, 8_000)
