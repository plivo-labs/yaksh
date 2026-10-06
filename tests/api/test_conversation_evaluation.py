from httpx import AsyncClient

from tests.conftest import Db, claim, evaluate_queued, finish, new_run
from yaksha.domain.conversations import CallOutcome, EndReason
from yaksha.domain.evaluations import Metric, MetricKey


async def test_a_conversations_metrics_follow_its_evaluation(client: AsyncClient, db: Db) -> None:
    run = await new_run(client, repeats=2)
    first, second = await claim(db), await claim(db)
    assert first is not None and second is not None
    none = (await client.get(f"/api/v1/conversations/{first}/evaluation")).json()
    assert (none["evaluation"], none["metrics"], none["items"], none["scenario_verdict"]) == (
        None,
        {},
        [],
        None,
    )
    await finish(db, first, CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP))
    await finish(db, second, CallOutcome(connected=False, end_reason=EndReason.USER_REQUEST))

    queued = (await client.get(f"/api/v1/conversations/{first}/evaluation")).json()
    assert (queued["evaluation"], queued["metrics"]) == ("queued", {})

    flagged = Metric(value={"unanswered": 1}, flags=["unanswered"])
    await evaluate_queued(db, {first: {MetricKey.TURN_TAKING: flagged}})

    done = (await client.get(f"/api/v1/conversations/{first}/evaluation")).json()
    assert (done["evaluation"], done["failure"]) == ("done", None)
    assert done["metrics"] == {"turn_taking": {"value": {"unanswered": 1}, "flags": ["unanswered"]}}
    listed = await client.get("/api/v1/conversations", params={"run_id": run["id"]})
    assert {c["id"]: c["evaluation"] for c in listed.json()["items"]} == {
        first: "done",
        second: None,
    }
