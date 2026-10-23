import asyncio
from typing import Any

from httpx import AsyncClient
from pipecat.classifiers.base_classifier import ClassifierError
from pipecat.classifiers.typesafe.jev.classifier import JevClassifier
from pipecat.classifiers.typesafe.jev.client import JevClient, JevUsage
from sqlalchemy import select

from tests.conftest import (
    Db,
    claim,
    create_agent_id,
    create_scenario,
    eventually,
    finish,
    make_evaluator,
    start_run,
)
from tests.evaluation.test_judged_calls import CALL, Judge
from yaksh.config import Settings
from yaksh.db.models import Evaluation, EvaluationItem, JudgeVersion
from yaksh.domain.conversations import CallOutcome, EndReason
from yaksh.domain.evaluations import DecidedBy, EvaluationState, Outcome
from yaksh.evaluation.jev import Jev, JevAnswer


class StubJevClient(JevClient):
    """Jev's client with set replies in Jev's own format, by item key: its choice and P(meets).
    The classifier on top of it maps the questions and the replies as it does for real."""

    def __init__(
        self, answers: dict[str, tuple[str, float]], *, broken: Exception | None = None
    ) -> None:
        super().__init__(api_key="test")
        self.answers = answers
        self.broken = broken
        self.questions: list[dict[str, Any]] = []

    async def ask(
        self, state: Any, questions: Any, assets: Any = None
    ) -> tuple[dict[str, dict[str, Any]], JevUsage]:
        self.questions.append(dict(questions))
        if self.broken is not None:
            raise self.broken
        used = JevUsage(input_tokens=1480, output_tokens=96)
        self.usage.input_tokens += used.input_tokens
        self.usage.output_tokens += used.output_tokens
        replies = {}
        for key in questions:
            choice, meets = self.answers[key]
            rest = round((1 - meets) / 3, 4)
            replies[key] = {
                "type": "choice",
                "choice": choice,
                "probabilities": {
                    "meets": meets,
                    "fails": rest,
                    "not_applicable": rest,
                    "cannot_tell": rest,
                },
                "confidence": meets,
            }
        return replies, used


def stub_jev(
    answers: dict[str, tuple[str, float]], *, broken: Exception | None = None
) -> tuple[Jev, StubJevClient]:
    client = StubJevClient(answers, broken=broken)
    return Jev(JevClassifier(client=client), 0.95), client


def test_jev_passes_only_a_confident_meets() -> None:
    assert JevAnswer("meets", {"meets": 0.96}).passes(0.95)
    assert not JevAnswer("meets", {"meets": 0.86}).passes(0.95)
    assert not JevAnswer("fails", {"meets": 0.99}).passes(0.95)


async def test_any_jev_failure_leaves_every_item_to_the_judge_model() -> None:
    busy, _ = stub_jev({}, broken=ClassifierError("Jev is busy (HTTP 529) after 4 attempts"))
    malformed, _ = stub_jev({}, broken=ValueError("usage holds a null"))

    assert await busy.ask("VIEW", {"criterion-1": "Reads the time back."}) is None
    assert await malformed.ask("VIEW", {"criterion-1": "Reads the time back."}) is None


async def judged_with(
    client: AsyncClient, db: Db, settings: Settings, jev: Jev
) -> tuple[Judge, Evaluation, dict[str, EvaluationItem]]:
    agent = await create_agent_id(
        client,
        name="Clinic",
        rules=[
            {"kind": "llm", "key": "promises", "name": "No promises", "applies_when": "a",
             "pass_when": "b", "fail_when": "c"},
        ],
    )  # fmt: skip
    scenario = await create_scenario(client, agent, criteria=["Reads the new time back."])
    assert (await start_run(client, agent, [scenario["id"]])).status_code == 202
    conversation = str(await claim(db))
    await finish(
        db,
        conversation,
        CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP),
        transcript=CALL,
    )
    judge = Judge()
    stop = asyncio.Event()
    evaluator = asyncio.create_task(make_evaluator(db, settings, judge, jev=jev).run(stop))

    async def done() -> Evaluation:
        async with db() as session:
            return await session.scalar(select(Evaluation)) or Evaluation()

    try:
        evaluation = await eventually(done, lambda e: e.state is EvaluationState.DONE)
    finally:
        stop.set()
        await evaluator
    async with db() as session:
        items = {item.item_key: item for item in await session.scalars(select(EvaluationItem))}
    return judge, evaluation, items


async def test_a_confident_jev_pass_needs_no_model_call_and_the_rest_keep_jevs_answer(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    jev, stub = stub_jev({"criterion-1": ("meets", 0.97), "rule-promises": ("fails", 0.05)})

    judge, evaluation, items = await judged_with(client, db, settings, jev)

    criterion, rule = items["criterion-1"], items["rule-promises"]
    [questions] = stub.questions
    assert list(questions) == ["criterion-1", "rule-promises"]
    assert questions["criterion-1"]["type"] == "choice"
    assert list(questions["criterion-1"]["criteria"]) == [
        "meets",
        "fails",
        "not_applicable",
        "cannot_tell",
    ]
    assert "Reads the new time back." in questions["criterion-1"]["instructions"]
    assert "criterion" not in judge.asked and "agent_rule" in judge.asked
    assert (criterion.decided_by, criterion.machine_outcome, criterion.answer) == (
        DecidedBy.JEV,
        Outcome.PASS,
        None,
    )
    assert (rule.decided_by, rule.machine_outcome, rule.jev_choice) == (
        DecidedBy.LLM,
        Outcome.FAIL,
        "fails",
    )
    async with db() as session:
        version = await session.scalar(select(JudgeVersion).where(JudgeVersion.judge == "jev"))
    assert version is not None and version.settings == {"pass_bar": 0.95}
    assert criterion.judge_version_id == version.id == rule.jev_version_id
    assert evaluation.jev_usage == {"input_tokens": 1480, "output_tokens": 96}
