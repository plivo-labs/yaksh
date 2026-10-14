import asyncio
import logging
import math
import os
import socket
import time
import uuid
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksh.config import Settings
from yaksh.db.models import Conversation
from yaksh.diagnostics import describe_exception
from yaksh.domain.conversations import (
    Admission,
    Caller,
    CallOutcome,
    CallRequest,
    ConversationStatus,
    EndReason,
    IncomingCall,
    StoredAudio,
    Transcript,
    audio_key,
)
from yaksh.domain.files import FileStore
from yaksh.domain.settings import AppSettings
from yaksh.domain.triggers import SEND_TIMEOUT_S
from yaksh.settings.store import SettingsSource
from yaksh.simulation import conversations
from yaksh.simulation.calls import CallerUnresponsiveError, LiveCall, run_call
from yaksh.simulation.workers import report_worker
from yaksh.timings import TIMINGS, Timings
from yaksh.worker.phone_account import PhoneAccount

log = logging.getLogger(__name__)

FINALIZE_ATTEMPTS = 5
FINALIZE_RETRY_S = 1.0
FINALIZE_TIMEOUT_S = 10.0
STORE_TIMEOUT_S = 60.0
"""For both audio files of a call: a 30-minute call, about 58 MB, at about 8 Mbit/s."""
MAX_BACKOFF_S = 30.0
DIAL_MARGIN_S = 60.0


async def wait_any(
    events: list[asyncio.Event], timeout: float | None, *extra: asyncio.Future[Any]
) -> None:
    """Return when any event is set, any extra future finishes, or the timeout passes."""
    waiters = [asyncio.ensure_future(event.wait()) for event in events]
    try:
        await asyncio.wait({*waiters, *extra}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


class Worker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        caller: Caller,
        settings: Settings,
        source: SettingsSource,
        account: PhoneAccount,
        store: FileStore,
        *,
        worker_id: str | None = None,
        timings: Timings = TIMINGS,
    ) -> None:
        """source gives the stored settings, read again at each poll when they changed; account
        follows the phone account in them."""
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.fatal = asyncio.Event()
        self._stop = asyncio.Event()
        self._sessionmaker = sessionmaker
        self._caller = caller
        self._settings = settings
        self._timings = timings
        self._source = source
        self._account = account
        self._store = store
        self._app = AppSettings()
        """The stored settings as of the latest poll."""
        self._reported_at = -math.inf
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._live: dict[uuid.UUID, LiveCall] = {}

    @property
    def active(self) -> int:
        return len(self._tasks)

    @property
    def stopping(self) -> bool:
        return self._stop.is_set() or self.fatal.is_set()

    async def run(self, stop: asyncio.Event) -> None:
        log.info("worker %s started", self.worker_id)
        self._stop = stop
        delay = self._timings.worker_poll_s
        try:
            while not self.stopping:
                poll = asyncio.ensure_future(self.poll())
                await wait_any([stop, self.fatal], self._timings.worker_lease_s, poll)
                if not poll.done():
                    if not self.stopping:
                        log.error(
                            "polling stalled for %ss; cancelling it", self._timings.worker_lease_s
                        )
                    await self._abandon(poll, "polling")
                    delay = min(delay * 2, MAX_BACKOFF_S)
                elif poll.exception() is None:
                    delay = self._timings.worker_poll_s
                else:
                    log.error("polling failed: %r; retrying in %.1fs", poll.exception(), delay)
                    delay = min(delay * 2, MAX_BACKOFF_S)
                await wait_any([stop, self.fatal], delay)
        finally:
            await self.drain()

    async def poll(self) -> int:
        self._app = await self._source.current()
        await self._account.refresh(self._app)
        async with self._sessionmaker() as session:
            reaped = await conversations.reap_expired(session, self._app.phone.number_rest_s)
        if reaped:
            log.warning("marked %d conversations failed after their lease expired", reaped)
        await self._report_if_due()
        claimed = 0
        lease_s = self._timings.worker_lease_s
        while self.active < self._settings.max_active_conversations and not self.stopping:
            await self._report_if_due()
            async with self._sessionmaker() as session:
                conversation = await conversations.claim_next(
                    session,
                    self.worker_id,
                    lease_s,
                    self._account.pool_app_id,
                    self._account.receiving_app_id,
                )
            if conversation is None:
                break
            sent = time.monotonic()
            renewal = await self._run_bounded(
                self._renew(conversation.id, None),
                lease_s,
                f"ownership check for {conversation.id}",
            )
            if renewal is None or renewal.exception() is not None:
                log.warning("could not confirm ownership of conversation %s", conversation.id)
                continue
            status = renewal.result()
            if status is None:
                log.warning("lost conversation %s before it started", conversation.id)
                continue
            if status is ConversationStatus.ENDING:
                await self._record_cancelled(conversation.id)
                continue
            try:
                request = await self._prepare(conversation)
            except conversations.PoolExhaustedError:
                # Another worker took the last free number between the claim and the lease.
                await self._requeue(conversation.id)
                continue
            except Exception as exc:
                log.exception("cannot prepare conversation %s", conversation.id)
                await self._record_failure(conversation.id, exc)
                continue
            if time.monotonic() - sent >= lease_s:
                log.warning("preparing conversation %s outlived the lease", conversation.id)
                continue
            self._start(request, confirmed_at=sent)
            claimed += 1
        return claimed

    async def _report_if_due(self) -> None:
        if time.monotonic() - self._reported_at < self._timings.worker_heartbeat_s:
            return
        async with self._sessionmaker() as session:
            await report_worker(
                session,
                self.worker_id,
                receiving_app_id=self._account.receiving_app_id,
                outbound_problem=self._account.outbound_problem,
                lease_s=self._timings.worker_lease_s,
            )
        self._reported_at = time.monotonic()

    async def _prepare(self, conversation: Conversation) -> CallRequest:
        async with self._sessionmaker() as session:
            return await conversations.prepare_call(
                session,
                self._app,
                conversation,
                self._account.pool_app_id,
                self._account.receiving_app_id,
            )

    async def _requeue(self, conversation_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session:
            returned = await conversations.requeue(session, conversation_id, self.worker_id)
        if not returned:
            await self._record_cancelled(conversation_id)

    async def _record_cancelled(self, conversation_id: uuid.UUID) -> None:
        outcome = CallOutcome(connected=False, end_reason=EndReason.USER_REQUEST)
        await self._record(conversation_id, outcome, Transcript(), StoredAudio())

    async def accept_incoming(self, call: IncomingCall) -> Admission | str:
        async with self._sessionmaker() as session:
            return await conversations.accept_incoming_call(session, self.worker_id, call)

    async def drain(self) -> None:
        """Ask every active call to stop, then wait for each task to finish recording its result."""
        for live in self._live.values():
            live.request_stop(EndReason.WORKER_STOPPED)
        tasks = list(self._tasks.values())
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=self._execute_bound())
        if not pending:
            return
        for task in pending:
            task.cancel()
        _, pending = await asyncio.wait(pending, timeout=self._timings.end_timeout_s * 2)
        if pending:
            log.critical("%d calls did not stop; abandoning them on exit", len(pending))

    def _execute_bound(self) -> float:
        """The longest _execute takes after a stop request.

        A bounded call end, the audio upload with its cancellation cleanup, every result write
        with its cancellation cleanup and retry delay, then the maintenance teardown.
        """
        end = self._timings.end_timeout_s
        return (
            end * 2
            + STORE_TIMEOUT_S
            + end
            + FINALIZE_ATTEMPTS * (FINALIZE_TIMEOUT_S + end + FINALIZE_RETRY_S)
            + end * 2
        )

    def _start(self, request: CallRequest, *, confirmed_at: float) -> None:
        live = LiveCall()
        self._live[request.conversation_id] = live
        task = asyncio.create_task(self._execute(request, live, confirmed_at))
        self._tasks[request.conversation_id] = task
        task.add_done_callback(lambda _: self._forget(request.conversation_id))

    def _forget(self, conversation_id: uuid.UUID) -> None:
        self._tasks.pop(conversation_id, None)
        self._live.pop(conversation_id, None)

    async def _execute(self, request: CallRequest, live: LiveCall, confirmed_at: float) -> None:
        """Run the call and record its result, holding the lease until the result is written."""
        maintenance = asyncio.create_task(
            self._maintain(request.conversation_id, live, confirmed_at)
        )
        try:
            outcome = await self._call(request, live)
            audio = await self._store_audio(request.conversation_id, outcome)
            await self._record(request.conversation_id, outcome, live.snapshot(), audio)
        finally:
            await self._abandon(
                maintenance,
                f"lease maintenance for {request.conversation_id}",
                timeout=self._timings.end_timeout_s * 2,
            )

    async def _call(self, request: CallRequest, live: LiveCall) -> CallOutcome:
        try:
            return await run_call(
                self._caller,
                request,
                live,
                end_timeout_s=self._timings.end_timeout_s,
                dial_timeout_s=self._connect_timeout_s(request),
            )
        except CallerUnresponsiveError:
            log.critical(
                "caller for conversation %s cannot be stopped; worker will exit",
                request.conversation_id,
            )
            self.fatal.set()
            return live.stop_ignored()
        except asyncio.CancelledError:
            return (
                live.outcome or CallOutcome(connected=live.connected, end_reason=live.end_reason)
            ).model_copy(update={"end_reason": EndReason.WORKER_STOPPED})
        except Exception as exc:
            log.exception("caller failed for conversation %s", request.conversation_id)
            return CallOutcome(
                connected=live.connected,
                end_reason=EndReason.ERROR,
                caller_error=describe_exception(exc),
            )

    def _connect_timeout_s(self, request: CallRequest) -> float:
        """How long a call may take to connect: ringing the agent, or for an outbound agent,
        its trigger and dial window."""
        outbound = request.agent.outbound
        if outbound is None:
            return request.app_settings.phone.ring_timeout_s + DIAL_MARGIN_S
        return SEND_TIMEOUT_S + outbound.dial_window_s + DIAL_MARGIN_S

    async def _store_audio(self, conversation_id: uuid.UUID, outcome: CallOutcome) -> StoredAudio:
        """Upload the call's audio files side by side. A file that fails is left out, and all
        are left out when the upload runs out of time; the call is kept either way."""
        what = f"storing the audio of conversation {conversation_id}"
        upload = await self._run_bounded(
            self._upload(conversation_id, outcome), STORE_TIMEOUT_S, what
        )
        if upload is None:
            log.error("%s timed out", what)
            return StoredAudio()
        return upload.result()

    async def _upload(self, conversation_id: uuid.UUID, outcome: CallOutcome) -> StoredAudio:
        recording_key, caller_voice_key = await asyncio.gather(
            self._put(audio_key(conversation_id, "recording.wav"), outcome.recording),
            self._put(audio_key(conversation_id, "caller-voice.wav"), outcome.caller_voice),
        )
        return StoredAudio(recording_key=recording_key, caller_voice_key=caller_voice_key)

    async def _put(self, key: str, data: bytes | None) -> str | None:
        """The key once the file is stored; None when there is no file or it failed."""
        if data is None:
            return None
        try:
            await self._store.put(key, data, "audio/wav")
        except Exception as error:
            log.error("storing %s failed: %r", key, error)
            return None
        return key

    async def _record_failure(self, conversation_id: uuid.UUID, exc: Exception) -> None:
        outcome = CallOutcome(
            connected=False, end_reason=EndReason.ERROR, caller_error=describe_exception(exc)
        )
        await self._record(conversation_id, outcome, Transcript(), StoredAudio())

    async def _record(
        self,
        conversation_id: uuid.UUID,
        outcome: CallOutcome,
        transcript: Transcript,
        audio: StoredAudio,
    ) -> None:
        what = f"recording conversation {conversation_id}"
        for attempt in range(1, FINALIZE_ATTEMPTS + 1):
            write = await self._run_bounded(
                self._write_result(conversation_id, outcome, transcript, audio),
                FINALIZE_TIMEOUT_S,
                what,
            )
            if write is None:
                if self.fatal.is_set():
                    return
                log.error("%s timed out (attempt %d)", what, attempt)
            elif write.exception() is not None:
                log.error("%s failed (attempt %d): %r", what, attempt, write.exception())
            elif not write.result():
                log.error("conversation %s was no longer ours when it finished", conversation_id)
                return
            else:
                return
            await asyncio.sleep(FINALIZE_RETRY_S)
        log.error("gave up %s; the reaper will mark it", what)

    async def _write_result(
        self,
        conversation_id: uuid.UUID,
        outcome: CallOutcome,
        transcript: Transcript,
        audio: StoredAudio,
    ) -> bool:
        async with self._sessionmaker() as session:
            return await conversations.finalize(
                session,
                conversation_id,
                self.worker_id,
                outcome,
                transcript,
                audio,
                self._app.phone.number_rest_s,
            )

    async def _maintain(
        self, conversation_id: uuid.UUID, live: LiveCall, confirmed_at: float
    ) -> None:
        """Renew the lease every heartbeat and flush evidence; stop the call on end or lost lease.

        The lease is measured from the moment a renewal was sent, never from when it returned.
        """
        lease_s = self._timings.worker_lease_s
        what = f"lease renewal for {conversation_id}"
        last_confirmed = confirmed_at
        while True:
            remaining = lease_s - (time.monotonic() - last_confirmed)
            await asyncio.sleep(min(self._timings.worker_heartbeat_s, max(remaining, 0.0)))
            remaining = lease_s - (time.monotonic() - last_confirmed)
            if remaining <= 0:
                log.warning("lease on conversation %s ran out; stopping the call", conversation_id)
                live.request_stop(EndReason.LEASE_LOST)
                return
            progress = live.snapshot() if live.dirty else None
            sent = time.monotonic()
            renewal = await self._run_bounded(
                self._renew(conversation_id, progress), remaining, what
            )
            if renewal is None:
                log.warning("lease on conversation %s ran out mid-renewal", conversation_id)
                live.request_stop(EndReason.LEASE_LOST)
                return
            if renewal.exception() is not None:
                log.error("%s failed: %r", what, renewal.exception())
                if progress is not None:
                    live.dirty = True
                continue
            last_confirmed = sent
            status = renewal.result()
            if status is None:
                log.warning("lost the lease on conversation %s", conversation_id)
                live.request_stop(EndReason.LEASE_LOST)
                return
            if status is ConversationStatus.ENDING:
                live.request_stop(EndReason.USER_REQUEST)

    async def _renew(
        self, conversation_id: uuid.UUID, progress: Transcript | None
    ) -> ConversationStatus | None:
        async with self._sessionmaker() as session:
            return await conversations.renew_lease(
                session, conversation_id, self.worker_id, self._timings.worker_lease_s, progress
            )

    async def _run_bounded[T](
        self, work: Coroutine[Any, Any, T], timeout: float, what: str
    ) -> asyncio.Future[T] | None:
        """Run `work` for at most `timeout` seconds: its finished future, or None once abandoned."""
        task = asyncio.ensure_future(work)
        try:
            await asyncio.wait({task}, timeout=timeout)
        except asyncio.CancelledError:
            await self._abandon(task, what)
            raise
        if task.done():
            return task
        await self._abandon(task, what)
        return None

    async def _abandon(
        self, task: asyncio.Future[Any], what: str, *, timeout: float | None = None
    ) -> bool:
        """Cancel with a bound. Returns False, and marks the worker fatal, when it will not stop."""
        task.cancel()
        try:
            await asyncio.wait({task}, timeout=timeout or self._timings.end_timeout_s)
        finally:
            if not task.done():
                log.critical("%s cannot be stopped; worker will exit", what)
                self.fatal.set()
        return task.done()
