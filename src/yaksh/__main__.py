import asyncio
import logging
import os
import signal
from functools import partial
from typing import TYPE_CHECKING

import typer
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine
from uvicorn.config import LOGGING_CONFIG

from yaksh.caller.plivo_server import PlivoServer, StreamRegistry, create_app
from yaksh.caller.unavailable import UnavailableCaller
from yaksh.config import Settings
from yaksh.db.migrate import upgrade_to_head
from yaksh.db.session import create_engine, create_sessionmaker
from yaksh.domain.agents import Transport
from yaksh.domain.conversations import Caller, CallObserver, CallOutcome, CallRequest
from yaksh.domain.errors import UnavailableError
from yaksh.integrations.s3 import S3FileStore
from yaksh.settings.cipher import Cipher, SecretUnreadableError
from yaksh.settings.store import SettingsSource
from yaksh.storage import file_store
from yaksh.timings import TIMINGS, Timings
from yaksh.worker.phone_account import PhoneAccount
from yaksh.worker.worker import Worker

if TYPE_CHECKING:
    from yaksh.caller.children import ChildConversations

cli = typer.Typer(no_args_is_help=True, add_completion=False)

API_LOGGING = {
    **LOGGING_CONFIG,
    "loggers": {
        **LOGGING_CONFIG["loggers"],
        "yaksh": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}


@cli.command()
def api(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    settings = Settings()
    uvicorn.run(
        "yaksh.api:create_app",
        factory=True,
        host=host or settings.api_host,
        port=port or settings.port or 8000,
        reload=reload,
        log_config=API_LOGGING,
    )


@cli.command()
def migrate() -> None:
    upgrade_to_head(str(Settings().database_url))


@cli.command()
def worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    upgrade_to_head(str(settings.database_url))
    registry = StreamRegistry()
    pool = call_processes(settings)
    asyncio.run(run_worker(settings, caller_of(settings, registry, pool), registry, pool=pool))


@cli.command()
def evaluator() -> None:
    """Measure and judge saved conversations, in a process of its own."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    upgrade_to_head(str(settings.database_url))
    asyncio.run(run_evaluator(settings))


async def settings_source(settings: Settings, engine: AsyncEngine) -> SettingsSource:
    """The stored settings, read once now: a YAKSH_ENCRYPTION_KEY that cannot decrypt them
    stops the process here, not at its first call."""
    source = SettingsSource(
        create_sessionmaker(engine), Cipher(settings.encryption_key.get_secret_value())
    )
    try:
        await source.current()
    except SecretUnreadableError as error:
        logging.critical("cannot read the stored settings: %s", error)
        raise SystemExit(1) from None
    return source


async def checked_file_store(settings: Settings) -> S3FileStore:
    """The file store, reached once now: wrong storage settings stop the process here, not at
    its first upload."""
    store = file_store(settings)
    try:
        await store.check()
    except UnavailableError as error:
        await store.close()
        logging.critical("%s", error)
        raise SystemExit(1) from None
    return store


async def run_evaluator(settings: Settings) -> None:
    from yaksh.worker.evaluator import Evaluator

    engine = create_engine(str(settings.database_url))
    source = await settings_source(settings, engine)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    store = await checked_file_store(settings)
    evaluator = Evaluator(create_sessionmaker(engine), settings, source, store)
    try:
        await evaluator.run(stop)
    finally:
        await evaluator.close()
        await store.close()
        if not await bounded_dispose(engine, TIMINGS.end_timeout_s):
            logging.shutdown()
            os._exit(1)


class TransportCaller:
    """Runs each call with the caller of its transport."""

    def __init__(self, phone: Caller, text: Caller) -> None:
        self._phone = phone
        self._text = text

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        caller = self._text if request.transport is Transport.TEXT else self._phone
        return await caller.run(request, observer, stop)


def call_processes(settings: Settings) -> ChildConversations | None:
    """The pool that holds each phone call in a process of its own, when the worker makes
    phone calls and YAKSH_CALL_PROCESSES asks for it."""
    if not settings.call_processes or settings.public_url is None:
        return None
    from yaksh.caller.children import ChildConversations

    return ChildConversations(str(settings.database_url))


def caller_of(
    settings: Settings, registry: StreamRegistry, pool: ChildConversations | None = None
) -> Caller:
    from yaksh.caller.phone import PhoneCaller
    from yaksh.caller.text import TextCaller

    text = TextCaller(settings)
    if settings.public_url is None:
        reason = "phone calls are off: set YAKSH_PUBLIC_URL to the address Plivo can reach"
        logging.warning(reason)
        return TransportCaller(UnavailableCaller(reason), text)
    return TransportCaller(PhoneCaller(settings, registry, conversations=pool), text)


def plivo_auth_token(source: SettingsSource) -> str | None:
    """The token Plivo signs its requests with, from the settings as last read."""
    latest = source.latest
    credentials = None if latest is None else latest.plivo_credentials
    return None if credentials is None else credentials[1]


async def run_worker(
    settings: Settings,
    caller: Caller,
    registry: StreamRegistry,
    timings: Timings = TIMINGS,
    pool: ChildConversations | None = None,
) -> None:
    """`pool` holds the phone calls in processes of their own; it is closed at the end."""
    engine = create_engine(str(settings.database_url))
    sessionmaker = create_sessionmaker(engine)
    source = await settings_source(settings, engine)
    store = await checked_file_store(settings)
    worker = Worker(
        sessionmaker,
        caller,
        source,
        PhoneAccount(sessionmaker, settings),
        store,
        timings=timings,
    )
    server = PlivoServer(
        create_app(
            registry, settings.public_url, partial(plivo_auth_token, source), worker.accept_incoming
        ),
        8770 if settings.port is None else settings.port,
    )
    await server.start()
    if pool is not None:
        pool.warm()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await worker.run(stop)
    finally:
        await server.stop(timings.end_timeout_s)
        await store.close()
        if (
            worker.fatal.is_set()
            or (pool is not None and not await pool.close())
            or not await bounded_dispose(engine, timings.end_timeout_s)
        ):
            # A leaked task or a call process left behind would keep the exit waiting forever.
            logging.shutdown()
            os._exit(1)


async def bounded_dispose(engine: AsyncEngine, timeout_s: float) -> bool:
    disposal = asyncio.ensure_future(engine.dispose())
    await asyncio.wait({disposal}, timeout=timeout_s)
    if disposal.done():
        return True
    disposal.cancel()
    await asyncio.wait({disposal}, timeout=timeout_s)
    return disposal.done()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
