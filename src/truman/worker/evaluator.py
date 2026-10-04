"""The evaluator: claims queued evaluations, computes them and stores the results. It runs as
a service of its own, so its work never shares the event loop of live calls."""

import asyncio
import contextlib
import logging
import os
import socket
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from truman.config import Settings
from truman.db.models import AgentVersion, Conversation, Evaluation
from truman.diagnostics import describe_exception
from truman.domain.agents import AgentConfig
from truman.evaluation import call, evaluations

log = logging.getLogger(__name__)

DRAIN_S = 8.0
"""How long a stopping evaluator waits for the evaluations it runs, within the 10 s that
Docker gives a container to stop. An evaluation it cancels is claimed again after its lease."""


class Evaluator:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self.evaluator_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._slots = asyncio.Semaphore(settings.evaluator_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

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
            async with self._sessionmaker() as session:
                conversation = await session.get_one(Conversation, evaluation.conversation_id)
                agent = await session.get_one(AgentVersion, conversation.agent_version_id)
            metrics = await call.evaluate(
                conversation, AgentConfig.model_validate(agent.config).agent_speaks_first
            )
            if not held.is_set():
                return
            async with self._sessionmaker() as session:
                if not await evaluations.finish(
                    session, evaluation.id, evaluation.claim_seq, metrics
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
