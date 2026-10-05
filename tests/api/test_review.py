import asyncio
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update

from tests.conftest import (
    Db,
    claim,
    create_agent_id,
    create_scenario,
    finish,
    start_run,
    wait_for_lock_waiters,
)
from truman.config import Settings
from truman.db.models import Evaluation, EvaluationItem
from truman.domain.conversations import CallOutcome, EndReason
from truman.domain.evaluations import DecidedBy, ItemRole, Outcome, Verdict
from truman.evaluation import evaluations, labels
from truman.evaluation.criteria import CRITERION
from truman.evaluation.evaluations import Evaluated
from truman.evaluation.judging import ItemResult
from truman.evaluation.verdicts import verdict


async def judged_calls(
    client: AsyncClient,
    db: Db,
    count: int,
    *,
    audit: bool,
    outcomes: tuple[Outcome, Outcome] = (Outcome.PASS, Outcome.PASS),
) -> list[str]:
    """Calls of one scenario with two criteria the judge model decided, and a phrase rule code
    passed."""
    agent = await create_agent_id(client, name=f"Shop {uuid.uuid4()}")
    scenario = await create_scenario(client, agent, criteria=["Greets.", "Books."])
    await start_run(client, agent, [scenario["id"]], repeats=count, max_retries=0)
    ids = [str(await claim(db)) for _ in range(count)]
    for conversation in ids:
        await finish(
            db, conversation, CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
        )
    criteria = [
        ItemResult(
            key=f"criterion-{number}",
            subject=text,
            judge="criterion",
            decided_by=DecidedBy.LLM,
            role=ItemRole.DECIDING,
            outcome=outcome,
        )
        for number, (text, outcome) in enumerate(
            zip(["Greets.", "Books."], outcomes, strict=True), 1
        )
    ]
    phrase = ItemResult(
        key="rule-name",
        subject="Says the name",
        judge=None,
        decided_by=DecidedBy.CODE,
        role=ItemRole.REPORTING,
        outcome=Outcome.PASS,
    )
    found = verdict((outcome, None) for outcome in outcomes)
    async with db() as session:
        versions = await evaluations.stored_judge_versions(
            session, [CRITERION.version("openai_compatible", "judge-1", {})]
        )
        while (evaluation := await evaluations.claim(session, "e1", 60)) is not None:
            await evaluations.finish(
                session,
                evaluation.id,
                evaluation.claim_seq,
                Evaluated(
                    metrics={},
                    items=[*criteria, phrase],
                    scenario_verdict=found,
                    conversation_verdict=found,
                    judge_versions=versions,
                ),
                audit=audit,
            )
    return ids


async def labeler(client: AsyncClient, name: str) -> dict[str, str]:
    created = await client.post("/api/v1/labelers", json={"name": name})
    assert created.status_code == 201, created.text
    return {"Authorization": f"Bearer {created.json()['token']}"}


async def shown(client: AsyncClient, headers: dict[str, str], call: str) -> dict[str, Any]:
    found = await client.get(f"/api/v1/review/conversations/{call}", headers=headers)
    assert found.status_code == 200, found.text
    return found.json()


async def label(
    client: AsyncClient, headers: dict[str, str], item_id: str, answer: str, reason: str
) -> dict[str, Any]:
    labeled = await client.post(
        f"/api/v1/review/items/{item_id}/labels",
        json={"answer": answer, "reason": reason},
        headers=headers,
    )
    assert labeled.status_code == 201, labeled.text
    return labeled.json()


async def agreement(client: AsyncClient) -> dict[str, Any]:
    return (await client.get("/api/v1/judges/agreement")).json()


async def test_an_audit_call_stays_blind_until_labeled_and_its_blind_labels_measure_the_judge(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=True)
    dana = await labeler(client, "dana")

    before = await shown(client, dana, call)

    assert (before["lane"], before["verdicts"], before["conversation"]["caller_reason"]) == (
        "audit",
        None,
        None,
    )
    assert [(item["blind"], item["machine"]) for item in before["items"]] == [
        (True, None),
        (True, None),
        (False, None),
    ]
    greets, books, _ = (item["id"] for item in before["items"])
    queued = (await client.get("/api/v1/review/queue", headers=dana)).json()
    assert [(entry["items"], entry["labeled"]) for entry in queued] == [(2, 0)]

    after_one = await label(client, dana, greets, "pass", "agent_error")

    assert [item["blind"] for item in after_one["items"]] == [False, True, False]
    assert after_one["items"][0]["machine"]["machine_outcome"] == "pass"
    assert (after_one["items"][2]["machine"], after_one["verdicts"]) == (None, None)
    assert after_one["items"][0]["label"]["blind"] is True

    after_both = await label(client, dana, books, "fail", "agent_error")

    assert after_both["items"][2]["machine"]["machine_outcome"] == "pass"
    assert after_both["verdicts"] == {
        "scenario_verdict": "pass",
        "conversation_verdict": "pass",
        "effective_scenario_verdict": "fail",
        "effective_conversation_verdict": "fail",
    }
    assert (await client.get("/api/v1/review/queue", headers=dana)).json() == []
    relabeled = await label(client, dana, books, "pass", "agent_error")
    assert relabeled["items"][1]["label"]["blind"] is False
    assert relabeled["verdicts"]["effective_scenario_verdict"] == "pass"
    measured = await agreement(client)
    assert [
        (v["judge"], v["items"]["count"], v["items"]["total"]) for v in measured["versions"]
    ] == [("criterion", 1, 2)]
    assert [
        (measured[key]["count"], measured[key]["total"])
        for key in ("conversations", "labelers", "offered_calls")
    ] == [(0, 1), (0, 0), (1, 1)]


async def test_agreement_counts_each_item_once_and_skips_items_the_judge_did_not_answer(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=True, outcomes=(Outcome.BLOCKED, Outcome.PASS))
    dana, sam = await labeler(client, "dana"), await labeler(client, "sam")
    greets, books, _ = (item["id"] for item in (await shown(client, dana, call))["items"])

    await label(client, dana, greets, "blocked", "caller_error")
    await label(client, dana, books, "pass", "agent_error")
    await label(client, sam, books, "fail", "agent_error")

    measured = await agreement(client)
    assert [(v["items"]["count"], v["items"]["total"]) for v in measured["versions"]] == [(1, 1)]
    assert [
        (measured[key]["count"], measured[key]["total"]) for key in ("conversations", "labelers")
    ] == [(1, 1), (0, 1)]


async def test_a_sampled_call_beyond_the_weekly_budget_takes_only_ad_hoc_labels(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    settings.audit_weekly_budget = 1
    calls = await judged_calls(client, db, 2, audit=True)
    beyond = max(calls, key=lambda call: labels.hash_fraction(uuid.UUID(call)))
    dana = await labeler(client, "dana")

    before = await shown(client, dana, beyond)
    labeled = await label(client, dana, before["items"][0]["id"], "fail", "agent_error")

    assert before["lane"] == "ad_hoc"
    assert all(not item["blind"] and item["machine"] for item in before["items"])
    assert (labeled["items"][0]["label"]["lane"], labeled["items"][0]["label"]["blind"]) == (
        "ad_hoc",
        False,
    )
    measured = await agreement(client)
    assert (measured["versions"], measured["offered_calls"]["total"]) == ([], 1)


async def test_a_labeler_who_saw_the_machine_results_first_gives_ad_hoc_labels(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=True)
    dana = await labeler(client, "dana")

    seen = await client.get(f"/api/v1/review/conversations/{call}?seen=true", headers=dana)
    greets = seen.json()["items"][0]["id"]
    labeled = await client.post(
        f"/api/v1/review/items/{greets}/labels", json={"answer": "pass", "seen": True}, headers=dana
    )

    assert seen.json()["lane"] == "ad_hoc"
    assert all(item["machine"] for item in seen.json()["items"])
    found = labeled.json()["items"][0]["label"]
    assert (found["lane"], found["blind"]) == ("ad_hoc", False)
    assert (await agreement(client))["versions"] == []


async def test_a_label_that_overturns_the_answer_in_view_says_why(
    client: AsyncClient, db: Db
) -> None:
    [shown_call] = await judged_calls(
        client, db, 1, audit=False, outcomes=(Outcome.FAIL, Outcome.PASS)
    )
    [blind_call] = await judged_calls(
        client, db, 1, audit=True, outcomes=(Outcome.FAIL, Outcome.PASS)
    )
    dana = await labeler(client, "dana")
    in_view = (await shown(client, dana, shown_call))["items"][0]["id"]
    blind = (await shown(client, dana, blind_call))["items"][0]["id"]

    def post(item: str, body: dict[str, str]) -> Any:
        return client.post(f"/api/v1/review/items/{item}/labels", json=body, headers=dana)

    bare = await post(in_view, {"answer": "pass"})
    why = await post(in_view, {"answer": "pass", "reason": "evidence_misread"})
    blind_bare = await post(blind, {"answer": "pass"})

    assert (bare.status_code, why.status_code, blind_bare.status_code) == (422, 201, 201)


async def test_a_label_on_a_hidden_item_needs_no_reason_so_it_reveals_nothing(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=True)
    dana = await labeler(client, "dana")
    phrase = (await shown(client, dana, call))["items"][2]

    labeled = await client.post(
        f"/api/v1/review/items/{phrase['id']}/labels",
        json={"answer": "not_applicable"},
        headers=dana,
    )

    assert (phrase["machine"], labeled.status_code) == (None, 201)


async def test_ad_hoc_labels_change_verdicts_and_disagreeing_labelers_leave_the_item_pending(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=False)
    dana, sam = await labeler(client, "dana"), await labeler(client, "sam")
    before = await shown(client, dana, call)

    assert (before["lane"], before["verdicts"]["scenario_verdict"]) == ("ad_hoc", "pass")
    assert all(not item["blind"] and item["machine"] for item in before["items"])
    greets = before["items"][0]["id"]

    await label(client, dana, greets, "fail", "agent_error")
    disputed = await label(client, sam, greets, "pass", "evidence_misread")

    assert disputed["items"][0]["machine"]["effective_outcome"] == "pending"
    assert disputed["verdicts"]["effective_scenario_verdict"] == "not_scored"
    measured = await agreement(client)
    assert (measured["versions"], measured["conversations"]["total"]) == ([], 0)


async def test_a_labeler_token_opens_only_the_review_routes_until_revoked(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=False)
    created = (await client.post("/api/v1/labelers", json={"name": "dana"})).json()
    dana = {"Authorization": f"Bearer {created['token']}"}

    assert (await client.get("/api/v1/agents", headers=dana)).status_code == 401
    assert (await client.get("/api/v1/judges/agreement", headers=dana)).status_code == 401
    assert (await client.get(f"/api/v1/review/conversations/{call}")).status_code == 401
    assert (await client.post("/api/v1/labelers", json={"name": "dana"})).status_code == 409
    assert (await client.get(f"/api/v1/review/conversations/{call}", headers=dana)).is_success

    assert (await client.delete(f"/api/v1/labelers/{created['id']}")).status_code == 204

    assert (
        await client.get(f"/api/v1/review/conversations/{call}", headers=dana)
    ).status_code == 401
    [listed] = (await client.get("/api/v1/labelers")).json()
    assert (listed["name"], listed["revoked_at"] is not None) == ("dana", True)

    renewed = (await client.post(f"/api/v1/labelers/{created['id']}/token")).json()

    again = {"Authorization": f"Bearer {renewed['token']}"}
    review = f"/api/v1/review/conversations/{call}"
    assert renewed["id"] == created["id"]
    assert (await client.get(review, headers=again)).is_success
    assert (await client.get(review, headers=dana)).status_code == 401


async def test_a_label_that_names_a_problem_needs_a_reason_and_other_needs_a_note(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=False)
    dana = await labeler(client, "dana")
    path = f"/api/v1/review/items/{(await shown(client, dana, call))['items'][0]['id']}/labels"

    sent = [
        {"answer": "pass"},
        {"answer": "fail"},
        {"answer": "fail", "reason": "other"},
        {"answer": "fail", "reason": "other", "note": "  "},
        {"answer": "fail", "reason": "other", "note": "The agent spoke Spanish."},
    ]
    found = [(await client.post(path, json=body, headers=dana)).status_code for body in sent]

    assert found == [201, 422, 422, 422, 201]


async def test_the_queue_offers_each_weeks_budget_in_hash_order(
    client: AsyncClient, db: Db
) -> None:
    calls = await judged_calls(client, db, 3, audit=True)
    created = (await client.post("/api/v1/labelers", json={"name": "dana"})).json()
    by_hash = sorted(calls, key=lambda call: labels.hash_fraction(uuid.UUID(call)))

    async with db() as session:
        offered = await labels.queue(session, uuid.UUID(created["id"]), budget=2)

    assert [str(entry.conversation_id) for entry in offered] == by_hash[:2]


async def test_a_label_waits_for_the_labels_before_it_and_counts_what_they_wrote(
    client: AsyncClient, db: Db
) -> None:
    [call] = await judged_calls(client, db, 1, audit=False)
    sam = await labeler(client, "sam")
    greets, books, _ = (item["id"] for item in (await shown(client, sam, call))["items"])

    async with db() as holder:
        await holder.execute(
            select(Evaluation)
            .where(Evaluation.conversation_id == uuid.UUID(call))
            .with_for_update()
        )
        labeling = asyncio.create_task(label(client, sam, books, "pass", "agent_error"))
        await wait_for_lock_waiters(db, 1)
        await holder.execute(
            update(EvaluationItem)
            .where(EvaluationItem.id == uuid.UUID(greets))
            .values(effective_outcome=Outcome.FAIL)
        )
        await holder.commit()
    labeled = await asyncio.wait_for(labeling, 10)

    assert labeled["verdicts"]["effective_scenario_verdict"] == "fail"
    async with db() as session:
        stored = await session.scalar(
            select(Evaluation.effective_scenario_verdict).where(
                Evaluation.conversation_id == uuid.UUID(call)
            )
        )
    assert stored is Verdict.FAIL
