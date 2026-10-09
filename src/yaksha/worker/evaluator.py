"""The evaluator: claims queued evaluations, computes them and stores the results. It runs as
a service of its own, so its work never shares the event loop of live calls."""

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pipecat.classifiers.jev.classifier import JevClassifier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksha.config import Settings
from yaksha.db.models import (
    AgentVersion,
    Conversation,
    Evaluation,
    PersonaVersion,
    ScenarioVersion,
)
from yaksha.db.models import Document as DocumentRow
from yaksha.diagnostics import describe_exception
from yaksha.domain.agents import AgentConfig
from yaksha.domain.files import FileStore
from yaksha.domain.language_models import JsonModel
from yaksha.domain.personas import PersonaConfig
from yaksha.domain.scenarios import ScenarioConfig
from yaksha.domain.settings import AppSettings, reveal
from yaksha.evaluation import call, evaluations, labels
from yaksha.evaluation.call import JUDGES, SOURCE_JUDGES, Judging
from yaksha.evaluation.jev import JEV, JEV_MODEL, Jev
from yaksha.evaluation.sources import Document
from yaksha.integrations.openai_models import OpenAIJsonModel
from yaksha.settings.store import SettingsSource

log = logging.getLogger(__name__)

DRAIN_S = 8.0
"""How long a stopping evaluator waits for the evaluations it runs, within the 10 s that
Docker gives a container to stop. An evaluation it cancels is claimed again after its lease."""


PROVIDER = "openai_compatible"


@dataclass(frozen=True)
class JudgeClients:
    """The clients that judge calls under one version of the settings. model is None while no
    LLM key is saved: calls then get the code metrics and phrase rules only."""

    model: JsonModel | None
    sources_model: JsonModel | None = None
    """Judges the agent's instructions and documents; model when None."""
    jev: Jev | None = None

    async def close(self) -> None:
        for client in (self.model, self.sources_model, self.jev):
            if client is not None:
                await client.close()


def judge_clients(settings: AppSettings) -> JudgeClients:
    """The judge model at the LLM provider, and Jev when a TypeSafe key is saved. The judges of
    the agent's whole instructions or documents get a longer timeout and one retry: their
    requests are large."""
    key = settings.secrets.llm_api_key
    if key is None:
        return JudgeClients(model=None)
    judges = settings.judges

    def model(*, sources: bool) -> OpenAIJsonModel:
        return OpenAIJsonModel.openai(
            key.get_secret_value(),
            judges.model,
            base_url=settings.llm.base_url,
            timeout_s=judges.sources_timeout_s if sources else judges.timeout_s,
            reasoning_effort=judges.reasoning_effort,
            retries=1 if sources else 3,
            max_output_tokens=judges.max_output_tokens,
        )

    jev = None
    if settings.secrets.typesafe_api_key is not None:
        classifier = JevClassifier(
            api_key=settings.secrets.typesafe_api_key.get_secret_value(), model=JEV_MODEL
        )
        jev = Jev(classifier, judges.jev_pass_bar)
    return JudgeClients(model(sources=False), model(sources=True), jev)


def judging_inputs(settings: AppSettings) -> tuple[object, ...]:
    """What the judging depends on; other changes to the settings keep the clients."""

    return (
        settings.llm.base_url,
        reveal(settings.secrets.llm_api_key),
        reveal(settings.secrets.typesafe_api_key),
        settings.judges,
    )


async def persona_prompt(session: AsyncSession, conversation: Conversation) -> str:
    version = await session.get_one(PersonaVersion, conversation.persona_version_id)
    return PersonaConfig.model_validate(version.config).prompt


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
        source: SettingsSource,
        store: FileStore,
        clients: Callable[[AppSettings], JudgeClients] = judge_clients,
    ) -> None:
        """clients builds the judge clients for a version of the stored settings."""
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._source = source
        self._store = store
        self._clients = clients
        self._judging: Judging | None = None
        self._judging_inputs: tuple[object, ...] | None = None
        self._in_use: list[JudgeClients] = []
        """Every client set built; one replaced by new settings may still serve an evaluation,
        so all are closed at the end."""
        self._prepared = asyncio.Lock()
        self.evaluator_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._slots = asyncio.Semaphore(settings.evaluator_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    async def close(self) -> None:
        for clients in self._in_use:
            await clients.close()

    async def _judging_for(self, settings: AppSettings) -> Judging | None:
        """The judging of these settings, built again when what it depends on changed."""
        async with self._prepared:
            inputs = judging_inputs(settings)
            if inputs != self._judging_inputs:
                clients = self._clients(settings)
                self._in_use.append(clients)
                self._judging = await self._prepare_judging(settings, clients)
                self._judging_inputs = inputs
            return self._judging

    async def _prepare_judging(self, app: AppSettings, clients: JudgeClients) -> Judging | None:
        if clients.model is None:
            log.warning(
                "no LLM provider key is saved: calls get code metrics and phrase rules only"
            )
            return None
        judges = app.judges
        settings = {
            "reasoning_effort": judges.reasoning_effort,
            "max_output_tokens": judges.max_output_tokens,
            "timeout_s": judges.timeout_s,
            "retries": 3,
        }
        sources = settings | {"timeout_s": judges.sources_timeout_s, "retries": 1}
        jev = clients.jev
        async with self._sessionmaker() as session:
            versions = await evaluations.stored_judge_versions(
                session,
                [
                    judge.version(
                        PROVIDER, judges.model, sources if judge in SOURCE_JUDGES else settings
                    )
                    for judge in JUDGES
                ]
                + (
                    [JEV.version("typesafe", jev.model, {"pass_bar": jev.pass_bar})]
                    if jev is not None
                    else []
                ),
            )
        log.info("judging with %s%s", judges.model, f", Jev first ({jev.model})" if jev else "")
        return Judging(
            model=clients.model,
            sources_model=clients.sources_model or clients.model,
            versions=versions,
            slots=asyncio.Semaphore(self._settings.evaluator_judge_concurrency),
            max_input_chars=judges.max_input_chars,
            jev=jev,
        )

    async def run(self, stop: asyncio.Event) -> None:
        log.info("evaluator %s started", self.evaluator_id)
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
            app = await self._source.current()
            judging = await self._judging_for(app)
            async with self._sessionmaker() as session:
                conversation = await session.get_one(Conversation, evaluation.conversation_id)
                agent = await session.get_one(AgentVersion, conversation.agent_version_id)
                scenario = await session.get_one(ScenarioVersion, conversation.scenario_version_id)
                agent_config = AgentConfig.model_validate(agent.config)
                judged = judging is not None and call.judged(conversation)
                persona = await persona_prompt(session, conversation) if judged else None
                documents = await knowledge_base(session, agent_config) if judged else []
            evaluated = await call.evaluate(
                conversation,
                self._store,
                agent_config,
                ScenarioConfig.model_validate(scenario.config),
                persona,
                documents,
                judging,
                retry_later=evaluation.attempts < evaluations.MAX_ATTEMPTS,
            )
            if not held.is_set():
                return
            async with self._sessionmaker() as session:
                audit = labels.hash_fraction(evaluation.conversation_id) < app.audit.sample_rate
                if not await evaluations.finish(
                    session, evaluation.id, evaluation.claim_seq, evaluated, audit=audit
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
