"""Phone conversations in processes of their own. Each call's audio pipeline runs in a child
process, so calls do not share one event loop and one interpreter lock, and a host's CPUs all
work. The worker keeps Plivo's requests and the stream's WebSocket, and relays the socket's
messages to the child."""

import asyncio
import logging
import multiprocessing
import queue
import signal
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from multiprocessing.process import BaseProcess
from typing import Any, cast

from fastapi import WebSocketDisconnect

from yaksh.caller import child
from yaksh.caller.child import ChildStart
from yaksh.caller.conversation import (
    Conversation,
    ConversationStart,
    Ended,
    Heard,
    Seat,
    waited,
)
from yaksh.caller.lag import LagTicker, worse
from yaksh.caller.link import Kind, Link, open_link
from yaksh.diagnostics import describe_exception
from yaksh.domain.conversations import Turn, WireEvent
from yaksh.domain.latency import LoopLag

log = logging.getLogger(__name__)

SPARES = 2
"""Processes kept ready beyond those that claimed calls hold; a burst starts the rest in about
two seconds, before the agent answers."""
PRELOAD = ["yaksh.__main__", child.__name__, "yaksh.caller.forkserver"]
"""What the forkserver imports before it forks call processes, so they share it. The worker's
main module is named, because the preload replaces CPython's default of `__main__`; the last
module freezes the rest."""
START_TIMEOUT_S = 10.0
"""A start normally takes milliseconds, and a burst of starts well under a second; one that
takes longer means the forkserver does not answer."""
READY_TIMEOUT_S = 60.0
"""A new process has the pipeline imported and the turn models loaded in seconds."""
TAKE_ATTEMPTS = 3
"""Processes a call tries before it fails: a broken set-up must not start them forever."""
CANCEL_KILL_S = 2.0
"""How long a cancelled conversation has to leave its result; a hang-up and the clean-up still
fit in the stop deadline after it."""
STREAM_SEND_LIMIT_S = 2.0
"""The longest a message to the stream may wait, from the child to Plivo, before the stream is
too slow for the call."""
STREAM_CLOSE_S = 0.5
"""How long a close waits for Plivo's answer, as Pipecat's own transport does."""
EXIT_TIMEOUT_S = 5.0
POOL_CLOSE_S = 10.0
STUCK = "call processes cannot start: the forkserver has not answered for {:.0f} s"


class ChildFailed(Exception):
    """The conversation's process failed, or stopped before the conversation finished."""


@dataclass(eq=False)
class Child:
    process: BaseProcess
    end: socket.socket
    """The worker's end of the socket pair."""
    link: Link | None = None
    """Opened when the worker starts to read the child's first message."""
    ready: asyncio.Future[None] | None = field(default=None, repr=False)
    """Done when the worker has read READY; failed with ChildFailed when it does not come."""
    reaped: asyncio.Future[None] | None = field(default=None, repr=False)


class Spawner:
    """One daemon thread that starts every call process. On Linux the forkserver dies with the
    thread that started it, so the thread lives as long as the process: the forkserver and the
    call processes die when the worker does. As a daemon, it cannot hold the worker's exit when
    a start never returns."""

    def __init__(self) -> None:
        self._jobs: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, name="yaksh-call-spawner", daemon=True)
        self._thread.start()

    def submit[T](self, work: Callable[[], T]) -> asyncio.Future[T]:
        """Run `work` on the thread; the future holds what it gives."""
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def settle(result: T | None, error: BaseException | None) -> None:
            if done.done():
                return
            if error is None:
                done.set_result(cast(T, result))
            else:
                done.set_exception(error)

        def job() -> None:
            try:
                result, error = work(), None
            except BaseException as raised:
                result, error = None, raised
            with suppress(RuntimeError):  # the loop closed while the worker stopped
                loop.call_soon_threadsafe(settle, result, error)

        self._jobs.put(job)
        return done

    def _run(self) -> None:
        while True:
            self._jobs.get()()


class ChildConversations:
    """Each conversation runs in a child process from a pool of warm ones. A call takes its child
    when it is claimed, so the child is ready by the time the stream opens. A child holds one
    call and leaves."""

    def __init__(self, database_url: str, target: Callable[..., Any] = child.main) -> None:
        """`target` runs in each child with its socket and whether it was preloaded."""
        if sys.platform == "darwin":
            # A forked child that uses macOS system frameworks crashes, so each child starts a
            # new interpreter there, as Python's default does.
            self._context = multiprocessing.get_context("spawn")
            self._preloaded = False
        else:
            self._context = multiprocessing.get_context("forkserver")
            self._context.set_forkserver_preload(PRELOAD)
            self._preloaded = True
        self.database_url = database_url
        self.lag = LagTicker()
        self._target = target
        self._spawner = Spawner()
        self._children: set[Child] = set()
        """Every process started and not reaped yet."""
        self._spares: deque[Child] = deque()
        self._spawning = 0
        self._starting: set[asyncio.Future[Child]] = set()
        self._reaps: set[asyncio.Future[None]] = set()
        """Kept apart from `_background`: closing the pool waits for them, it never cancels
        them."""
        self._stuck_since: float | None = None
        self._closed = False
        self._background: set[asyncio.Future[Any]] = set()

    def warm(self) -> None:
        """Start processes until the spares, with those starting, reach SPARES. The worker calls
        it once its event loop runs, and each call that starts calls it again."""
        if self._closed or self._stuck_since is not None:
            return
        for _ in range(SPARES - len(self._spares) - self._spawning):
            self._spawning += 1
            self._keep(asyncio.ensure_future(self._add_spare()))

    def reserve(self) -> Seat:
        """Raises ChildFailed at once while the pool is stuck, so no call is dialed that no
        process can hold."""
        if self._stuck_since is not None:
            raise ChildFailed(STUCK.format(time.monotonic() - self._stuck_since))
        return ChildSeat(self, self._keep(asyncio.ensure_future(self._take())))

    async def close(self) -> bool:
        """Stop starting processes, kill every one left and wait for them to exit, for at most
        POOL_CLOSE_S. False when something is left: with a forkserver that does not answer, a
        start or a process's exit report never comes."""
        self._closed = True
        for future in self._background:
            future.cancel()
        deadline = time.monotonic() + POOL_CLOSE_S
        starting: set[asyncio.Future[Child]] = set()
        if self._starting:  # a start that ends now gives its process to `discard`
            _, starting = await asyncio.wait(set(self._starting), timeout=POOL_CLOSE_S)
        for left in list(self._children):
            self.discard(left, "the worker stops")
        reaping: set[asyncio.Future[None]] = set()
        if self._reaps:
            left_s = max(0.0, deadline - time.monotonic())
            _, reaping = await asyncio.wait(set(self._reaps), timeout=left_s)
        return not starting and not reaping and self._stuck_since is None

    def discard(self, taken: Child, reason: str) -> None:
        """Kill a child now, dropping its link with anything still queued, and reap it in the
        background."""
        if taken.reaped is None:
            log.info("killing call process %s: %s", taken.process.pid, reason)
        taken.process.kill()
        if taken.link is not None:
            taken.link.abort()
        self._reap(taken, close_link=False)

    def retire(self, taken: Child) -> None:
        """A child that sent its result leaves by itself: close the link and reap it."""
        self._reap(taken, close_link=True)

    def give_back(self, taken: Child, reason: str) -> None:
        """A process that no call holds waits for the next call, ready or still starting,
        unless the spares are full; then it is killed for `reason`."""
        if self._closed or len(self._spares) + self._spawning >= SPARES:
            self.discard(taken, reason)
        else:
            self._spares.appendleft(taken)
            log.info("call process %s waits for the next call", taken.process.pid)

    def _reap(self, taken: Child, close_link: bool) -> None:
        if taken.reaped is None:
            taken.reaped = asyncio.ensure_future(self._reaping(taken, close_link))
            self._reaps.add(taken.reaped)
            taken.reaped.add_done_callback(self._reaps.discard)

    async def _reaping(self, taken: Child, close_link: bool) -> None:
        try:
            if close_link and taken.link is not None:
                await taken.link.close()
            if not await exited(taken.process, EXIT_TIMEOUT_S):
                taken.process.kill()
                if not await exited(taken.process, EXIT_TIMEOUT_S):
                    log.warning("call process %s did not exit after a kill", taken.process.pid)
                    return
            code = taken.process.exitcode
            if code not in (0, -signal.SIGKILL):
                log.warning("call process %s left with exit code %s", taken.process.pid, code)
        finally:
            taken.end.close()
            self._children.discard(taken)

    def _keep[T](self, future: asyncio.Future[T]) -> asyncio.Future[T]:
        """Hold a reference to a background future until it is done."""
        self._background.add(future)
        future.add_done_callback(self._background.discard)
        return future

    def _spawn(self) -> Child:
        """On the spawner thread."""
        end, child_end = socket.socketpair()
        try:
            process = self._context.Process(
                target=self._target,
                args=(child_end, self._preloaded),
                name="yaksh-call",
                daemon=True,
            )
            process.start()
        except BaseException:
            end.close()
            raise
        finally:
            child_end.close()
        return Child(process, end)

    async def _spawned(self) -> Child:
        """A new process. A start that does not return within START_TIMEOUT_S marks the pool
        stuck: later reservations fail at once until it returns. The process of a start that
        nobody waits for any more is killed once it exists."""
        if self._closed:
            raise ChildFailed("the worker stops")
        if self._stuck_since is not None:
            raise ChildFailed(STUCK.format(time.monotonic() - self._stuck_since))
        done = self._spawner.submit(self._spawn)
        self._starting.add(done)
        done.add_done_callback(self._starting.discard)
        try:
            await asyncio.wait({done}, timeout=START_TIMEOUT_S)
        except asyncio.CancelledError:
            done.add_done_callback(self._unwanted)
            raise
        if not done.done():
            if self._stuck_since is None:
                self._stuck_since = time.monotonic()
                log.error(
                    "a call process did not start in %.0f s; phone calls fail until one does",
                    START_TIMEOUT_S,
                )
            done.add_done_callback(self._late)
            raise ChildFailed(STUCK.format(START_TIMEOUT_S))
        try:
            spawned = done.result()
        except Exception as error:
            raise ChildFailed(
                f"a call process could not start: {describe_exception(error)}"
            ) from error
        self._adopt(spawned)
        return spawned

    def _adopt(self, spawned: Child) -> None:
        """Track a new process and start to read its READY."""
        self._children.add(spawned)
        log.info("started call process %s", spawned.process.pid)
        spawned.ready = self._keep(asyncio.ensure_future(self._get_ready(spawned)))
        spawned.ready.add_done_callback(lambda ready: self._not_ready(spawned, ready))

    async def _get_ready(self, spawned: Child) -> None:
        started = time.monotonic()
        try:
            async with asyncio.timeout(READY_TIMEOUT_S):
                spawned.link = await open_link(spawned.end)
                kind, _ = await spawned.link.receive()
        except Exception as error:
            raise ChildFailed(f"it did not get ready: {describe_exception(error)}") from error
        if kind is not Kind.READY:
            raise ChildFailed(f"it sent {kind.name} before it was ready")
        log.info(
            "call process %s is ready in %.1f s", spawned.process.pid, time.monotonic() - started
        )

    def _not_ready(self, spawned: Child, ready: asyncio.Future[None]) -> None:
        """Kill a process that did not get ready, also while it waits as a spare."""
        if ready.cancelled() or ready.exception() is None:
            return
        if spawned in self._spares:
            self._spares.remove(spawned)
        self.discard(spawned, str(ready.exception()))

    def _late(self, done: asyncio.Future[Child]) -> None:
        """The start that marked the pool stuck has returned."""
        self._stuck_since = None
        log.info("call processes start again")
        self._unwanted(done)

    def _unwanted(self, done: asyncio.Future[Child]) -> None:
        """Give the process of a start that nobody waits for any more to the pool."""
        if not done.cancelled() and done.exception() is None:
            spawned = done.result()
            self._adopt(spawned)
            self.give_back(spawned, "nobody waits for it")

    async def _take(self) -> Child:
        """A ready process for a call. Cancelled, it gives the process it was getting to the
        pool as it is."""
        for _ in range(TAKE_ATTEMPTS):
            taken = self._spare() or await self._spawned()
            assert taken.ready is not None
            try:
                await asyncio.wait({taken.ready})
            except asyncio.CancelledError:
                self.give_back(taken, "its call was given up")
                raise
            if taken.ready.cancelled() or taken.ready.exception() is not None:
                continue  # `_not_ready` has killed it, or the pool closes
            return taken
        raise ChildFailed(f"no call process got ready in {TAKE_ATTEMPTS} tries")

    def _spare(self) -> Child | None:
        """The next spare that still runs. One that stopped while it waited is dropped: its exit
        was reported, or its end of the socket is closed."""
        while self._spares:
            spare = self._spares.popleft()
            if spare.process.is_alive() and not (spare.link is not None and spare.link.at_eof()):
                return spare
            self.discard(spare, "it stopped while it waited for a call")
        return None

    async def _add_spare(self) -> None:
        try:
            spare = await self._spawned()
        except ChildFailed as error:
            log.warning("could not start a spare call process: %s", error)
            return
        finally:
            self._spawning -= 1
        if self._closed:
            self.discard(spare, "the worker stops")
        else:
            self._spares.append(spare)


class ChildSeat:
    def __init__(self, pool: ChildConversations, taking: asyncio.Future[Child]) -> None:
        self._pool = pool
        self._taking: asyncio.Future[Child] | None = taking
        """None once the conversation or the release has the child."""

    async def start(self, start: ConversationStart) -> Conversation:
        assert self._taking is not None, "a seat holds one conversation"
        taken = await waited(self._taking)
        self._taking = None
        conversation = ChildConversation(self._pool, taken, start)
        try:
            await conversation.open()
        except BaseException:
            await conversation.close()
            raise
        self._pool.warm()
        return conversation

    async def release(self) -> None:
        """A call that never started leaves its process to the pool: a take that still runs is
        cancelled, and gives the process to the pool as it is."""
        taking, self._taking = self._taking, None
        if taking is None:
            return
        if not taking.done():
            taking.cancel()
        elif not taking.cancelled() and taking.exception() is None:
            self._pool.give_back(taking.result(), "its call never started")


class ChildConversation:
    def __init__(self, pool: ChildConversations, taken: Child, start: ConversationStart) -> None:
        assert taken.link is not None
        self._pool = pool
        self._child = taken
        self._link = taken.link
        self._start = start
        loop = asyncio.get_running_loop()
        self._ended: asyncio.Future[Ended] = loop.create_future()
        self._heard: asyncio.Future[Heard] = loop.create_future()
        self._outbox: asyncio.Queue[tuple[float, dict[str, Any]]] = asyncio.Queue()
        self._watch = pool.lag.watch(start.clock.ms)
        self._worker_lag: LoopLag | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._deadline: asyncio.TimerHandle | None = None
        self._relayed_in = 0
        self._relayed_out = 0

    async def open(self) -> None:
        start = self._start
        log.info(
            "conversation %s runs in call process %s",
            start.request.conversation_id,
            self._child.process.pid,
        )
        await self._link.send(
            Kind.START,
            ChildStart(
                request=start.request,
                keys=start.keys,
                clock=start.clock.origin,
                stream_id=start.dialed.stream_id,
                call_uuid=start.dialed.call_uuid,
                encoding=start.dialed.encoding,
                connected_ms=start.connected_ms,
                database_url=self._pool.database_url,
            ),
        )
        self._tasks = [
            asyncio.create_task(self._listen()),
            asyncio.create_task(self._write_stream()),
            asyncio.create_task(self._forward()),
            asyncio.create_task(self._pass_stop()),
        ]
        self._tasks += [
            asyncio.create_task(self._pass_speech(index, item))
            for index, item in enumerate(start.prepared.items)
        ]

    async def ended(self) -> Ended:
        return await waited(self._ended)

    def cancel(self) -> None:
        """The child ends the conversation as worker_stopped and sends its result; a child that
        has not sent it within CANCEL_KILL_S is killed."""
        self._link.post(Kind.CANCEL, None)
        if self._deadline is None and not self._heard.done():
            self._deadline = asyncio.get_running_loop().call_later(CANCEL_KILL_S, self._kill)

    async def heard(self) -> Heard:
        return await waited(self._heard)

    async def close(self) -> None:
        self._disarm()
        self._pool.lag.unwatch(self._watch)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        log.info(
            "conversation %s relayed %d in, %d out",
            self._start.request.conversation_id,
            self._relayed_in,
            self._relayed_out,
        )
        if self._heard.done() and not self._heard.cancelled() and self._heard.exception() is None:
            self._pool.retire(self._child)
        else:
            self._pool.discard(self._child, "its conversation did not finish")

    def _disarm(self) -> None:
        if self._deadline is not None:
            self._deadline.cancel()

    def _kill(self) -> None:
        self._fail("the call process did not stop when the call was cancelled")
        self._pool.discard(self._child, f"it did not stop within {CANCEL_KILL_S:.0f} s of a cancel")

    def _fail(self, reason: str) -> None:
        for future in (self._ended, self._heard):
            if not future.done():
                future.set_exception(ChildFailed(reason))
                future.exception()  # a failure reaches the call once, through ended()

    async def _listen(self) -> None:
        """What the child sends: the stream's outgoing messages, the observer's calls, and the
        end of the conversation. Messages for the stream go to their own writer, so a slow
        stream never holds the end of the conversation back."""
        observer = self._start.observer
        try:
            while True:
                kind, payload = await self._link.receive()
                if kind is Kind.SOCKET:
                    self._outbox.put_nowait((time.monotonic(), cast(dict[str, Any], payload)))
                elif kind is Kind.TURN:
                    observer.turn(cast(Turn, payload))
                elif kind is Kind.WIRE:
                    observer.wire_event(cast(WireEvent, payload))
                elif kind is Kind.ENDED:
                    ended = cast(Ended, payload)
                    self._worker_lag = self._pool.lag.unwatch(self._watch, ended.at_ms)
                    self._ended.set_result(ended)
                elif kind is Kind.HEARD:
                    heard = cast(Heard, payload)
                    loop_lag = worse(heard.loop_lag, self._worker_lag)
                    self._heard.set_result(replace(heard, loop_lag=loop_lag))
                    return
                elif kind is Kind.FAILED:
                    self._fail(f"the call process failed: {payload}")
                    return
        except asyncio.IncompleteReadError, OSError:
            self._fail("the call process stopped before the call ended")
        finally:
            self._disarm()

    async def _write_stream(self) -> None:
        """The child's messages to the stream, in order. A message that Plivo has not taken
        within STREAM_SEND_LIMIT_S of reaching the worker fails the call: the stream is too
        slow for it. A close waits STREAM_CLOSE_S at most and never fails the call."""
        stream = self._start.dialed.socket
        while True:
            arrived, message = await self._outbox.get()
            if message["type"] == "websocket.close":
                with suppress(WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
                    await asyncio.wait_for(stream.send(message), STREAM_CLOSE_S)
                return
            try:
                left = STREAM_SEND_LIMIT_S - (time.monotonic() - arrived)
                await asyncio.wait_for(stream.send(message), max(left, 0.0))
            except TimeoutError:
                reason = f"the stream did not take audio within {STREAM_SEND_LIMIT_S:.0f} s"
                self._fail(reason)
                self._pool.discard(self._child, reason)
                return
            except WebSocketDisconnect, RuntimeError, OSError:
                return  # the stream is gone; its reader gives the child the disconnect
            self._relayed_out += 1

    async def _forward(self) -> None:
        """The stream's incoming messages, until it disconnects."""
        stream = self._start.dialed.socket
        while True:
            try:
                message = await stream.receive()
            except (WebSocketDisconnect, RuntimeError, OSError) as error:
                log.info("the stream stopped giving messages: %r", error)
                message = {"type": "websocket.disconnect", "code": 1006}
            self._relayed_in += 1
            try:
                await self._link.send(Kind.SOCKET, message)
            except OSError:
                return
            if message["type"] == "websocket.disconnect":
                return

    async def _pass_stop(self) -> None:
        await self._start.stop.wait()
        with suppress(OSError):
            await self._link.send(Kind.STOP, None)

    async def _pass_speech(self, index: int, item: asyncio.Future[bytes]) -> None:
        try:
            made: bytes | BaseException = await waited(item)
        except Exception as error:
            made = error
        with suppress(OSError):
            await self._link.send(Kind.SPEECH, (index, made))


async def exited(process: BaseProcess, timeout: float) -> bool:
    """Wait for a process to exit without holding a thread: the event loop watches its
    sentinel, which turns readable when the process ends."""
    loop = asyncio.get_running_loop()
    readable = loop.create_future()

    def ready() -> None:
        if not readable.done():
            readable.set_result(None)

    deadline = time.monotonic() + timeout
    loop.add_reader(process.sentinel, ready)
    try:
        await asyncio.wait_for(readable, timeout)
    except TimeoutError:
        return False
    finally:
        loop.remove_reader(process.sentinel)
    while process.exitcode is None:  # the exit status can follow the sentinel by a moment
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True
