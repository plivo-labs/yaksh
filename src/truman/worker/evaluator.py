"""The evaluator: claims queued evaluations, computes them and stores the results. It runs as
a service of its own, so its work never shares the event loop of live calls."""

import asyncio
import contextlib
import logging
import os
import socket
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from truman.config import Settings
from truman.db.models import AgentVersion, Conversation, Evaluation, ScenarioVersion
from truman.db.models import Document as DocumentRow
from truman.diagnostics import describe_exception
from truman.domain.agents import AgentConfig
from truman.domain.language_models import JsonModel, ModelCallError
from truman.domain.scenarios import ScenarioConfig
from truman.evaluation import call, evaluations
from truman.evaluation.call import JUDGES, SOURCE_JUDGES, Judging
from truman.evaluation.sources import Document
from truman.integrations.openai_models import OpenAIJsonModel

log = logging.getLogger(__name__)

DRAIN_S = 8.0
"""How long a stopping evaluator waits for the evaluations it runs, within the 10 s that
Docker gives a container to stop. An evaluation it cancels is claimed again after its lease."""


PROBE = {
    "type": "object",
    "properties": {"yes": {"type": "boolean"}},
    "required": ["yes"],
    "additionalProperties": False,
}
"""A first question at start, so a judge model that cannot answer stops the evaluator at once
instead of failing every item."""
PROBE_TIMEOUT_S = 20.0
PROVIDER = "openai_compatible"


def judge_model(settings: Settings, *, sources: bool = False) -> OpenAIJsonModel | None:
    """The model that judges calls; None when no model or key is set. The judges of the agent's
    whole instructions or documents get a longer timeout and one retry: their requests are
    large."""
    key = settings.judge_openai_api_key or settings.openai_api_key
    if not settings.judge_llm_model or key is None:
        return None
    return OpenAIJsonModel.openai(
        key.get_secret_value(),
        settings.judge_llm_model,
        base_url=settings.judge_openai_base_url or settings.openai_base_url,
        timeout_s=settings.judge_sources_timeout_s if sources else settings.judge_llm_timeout_s,
        reasoning_effort=settings.judge_llm_reasoning_effort,
        retries=1 if sources else 3,
        max_output_tokens=settings.judge_max_output_tokens,
    )


async def knowledge_base(session: AsyncSession, agent: AgentConfig) -> list[Document]:
    """The agent's knowledge-base documents, each under the name the agent gives it, in its
    order."""
    ids = [entry.document_id for entry in agent.knowledge_base]
    if not ids:
        return []
    rows = await session.execute(
        select(DocumentRow.id, DocumentRow.text).where(DocumentRow.id.in_(ids))
    )
    texts = dict(rows.tuples().all())
    return [
        Document(name=entry.name, text=texts[entry.document_id])
        for entry in agent.knowledge_base
        if entry.document_id in texts
    ]


class Evaluator:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        model: JsonModel | None = None,
        sources_model: JsonModel | None = None,
    ) -> None:
        """model judges calls; None runs the code metrics and phrase rules only. sources_model
        judges the agent's instructions and documents; model when None."""
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._model = model
        self._sources_model = sources_model
        self._judging: Judging | None = None
        self.evaluator_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._slots = asyncio.Semaphore(settings.evaluator_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    async def _prepare_judging(self) -> Judging | None:
        if self._model is None:
            log.warning("no judge model is set: calls get code metrics and phrase rules only")
            return None
        settings = {
            "reasoning_effort": self._settings.judge_llm_reasoning_effort,
            "max_output_tokens": self._settings.judge_max_output_tokens,
            "timeout_s": self._settings.judge_llm_timeout_s,
            "retries": 3,
        }
        sources = settings | {"timeout_s": self._settings.judge_sources_timeout_s, "retries": 1}
        model = self._settings.judge_llm_model
        try:
            await asyncio.wait_for(
                self._model.complete_json(
                    system="Answer the question.",
                    user="Is this a test?",
                    name="probe",
                    schema=PROBE,
                ),
                PROBE_TIMEOUT_S,
            )
        except TimeoutError:
            log.warning("the judge model %s did not answer a first check in time", model)
        except ModelCallError as error:
            if not error.temporary:
                raise RuntimeError(
                    f"the judge model {model} cannot be used ({error}); set JUDGE_LLM_MODEL to "
                    "a model the judge endpoint has, or to an empty value to turn judging off"
                ) from error
            log.warning("the judge model %s did not answer a first check: %s", model, error)
        async with self._sessionmaker() as session:
            versions = await evaluations.stored_judge_versions(
                session,
                [
                    judge.version(PROVIDER, model, sources if judge in SOURCE_JUDGES else settings)
                    for judge in JUDGES
                ],
            )
        log.info("judging with %s", model)
        return Judging(
            model=self._model,
            sources_model=self._sources_model or self._model,
            versions=versions,
            slots=asyncio.Semaphore(self._settings.evaluator_judge_concurrency),
            max_input_chars=self._settings.judge_max_input_chars,
        )

    async def run(self, stop: asyncio.Event) -> None:
        log.info("evaluator %s started", self.evaluator_id)
        self._judging = await self._prepare_judging()
        try:
            while not stop.is_set():
                try:
                    claimed = await self.poll(stop)
                except Exception:
                    log.exception("claiming evaluations failed")
                    claimed = 0
                if not claimed:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            stop.wait(), self._settings.evaluator_poll_interval_s
                        )
            if self._tasks:
                await asyncio.wait(self._tasks, timeout=DRAIN_S)
        finally:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def poll(self, stop: asyncio.Event) -> int:
        """Claim evaluations while a slot is free; return how many were claimed."""
        claimed = 0
        while not stop.is_set() and not self._slots.locked():
            async with self._sessionmaker() as session:
                evaluation = await evaluations.claim(
                    session, self.evaluator_id, self._settings.evaluator_lease_s
                )
            if evaluation is None:
                break
            await self._slots.acquire()
            task = asyncio.create_task(self._evaluate(evaluation))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            claimed += 1
        return claimed

    async def _evaluate(self, evaluation: Evaluation) -> None:
        held = asyncio.Event()
        held.set()
        heartbeat = asyncio.create_task(self._keep(evaluation, held))
        try:
            async with self._sessionmaker() as session:
                conversation = await session.get_one(Conversation, evaluation.conversation_id)
                agent = await session.get_one(AgentVersion, conversation.agent_version_id)
                scenario = await session.get_one(ScenarioVersion, conversation.scenario_version_id)
                agent_config = AgentConfig.model_validate(agent.config)
                judged = self._judging is not None and call.judged(conversation)
                documents = await knowledge_base(session, agent_config) if judged else []
            evaluated = await call.evaluate(
                conversation,
                agent_config,
                ScenarioConfig.model_validate(scenario.config),
                documents,
                self._judging,
                retry_later=evaluation.attempts < evaluations.MAX_ATTEMPTS,
            )
            if not held.is_set():
                return
            async with self._sessionmaker() as session:
                if not await evaluations.finish(
                    session, evaluation.id, evaluation.claim_seq, evaluated
                ):
                    log.warning(
                        "evaluation %s was claimed again; dropped its results", evaluation.id
                    )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.exception("evaluation %s failed", evaluation.id)
            await self._fail(evaluation, describe_exception(error))
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            self._slots.release()

    async def _fail(self, evaluation: Evaluation, failure: str) -> None:
        try:
            async with self._sessionmaker() as session:
                await evaluations.fail(
                    session, evaluation.id, evaluation.claim_seq, evaluation.attempts, failure
                )
        except Exception:
            log.exception("recording the failure of evaluation %s failed", evaluation.id)

    async def _keep(self, evaluation: Evaluation, held: asyncio.Event) -> None:
        """Renew the lease while the evaluation runs; clear held when another evaluator has
        claimed it since. A renewal that fails is tried again at the next beat."""
        lease_s = self._settings.evaluator_lease_s
        while True:
            await asyncio.sleep(lease_s / 3)
            try:
                async with self._sessionmaker() as session:
                    renewed = await evaluations.renew(
                        session, evaluation.id, evaluation.claim_seq, lease_s
                    )
            except Exception:
                log.exception("renewing the lease of evaluation %s failed", evaluation.id)
                continue
            if not renewed:
                held.clear()
                return
