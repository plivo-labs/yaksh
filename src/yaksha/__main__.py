import asyncio
import logging
import os
import signal
from functools import partial

import typer
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine
from uvicorn.config import LOGGING_CONFIG

from yaksha.caller.plivo_server import PlivoServer, StreamRegistry, create_app
from yaksha.caller.unavailable import UnavailableCaller
from yaksha.config import Settings
from yaksha.db.migrate import upgrade_to_head
from yaksha.db.session import create_engine, create_sessionmaker
from yaksha.domain.conversations import Caller
from yaksha.settings.cipher import Cipher, SecretUnreadableError
from yaksha.settings.store import SettingsSource
from yaksha.storage import file_store
from yaksha.worker.phone_account import PhoneAccount
from yaksha.worker.worker import Worker

cli = typer.Typer(no_args_is_help=True, add_completion=False)

API_LOGGING = {
    **LOGGING_CONFIG,
    "loggers": {
        **LOGGING_CONFIG["loggers"],
        "yaksha": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}


@cli.command()
def api(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    settings = Settings()
    uvicorn.run(
        "yaksha.api:create_app",
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
    asyncio.run(run_worker(settings, caller_of(settings, registry), registry))


@cli.command()
def evaluator() -> None:
    """Measure and judge saved conversations, in a process of its own."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    upgrade_to_head(str(settings.database_url))
    asyncio.run(run_evaluator(settings))


async def settings_source(settings: Settings, engine: AsyncEngine) -> SettingsSource:
    """The stored settings, read once now: a YAKSHA_ENCRYPTION_KEY that cannot decrypt them
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


async def run_evaluator(settings: Settings) -> None:
    from yaksha.worker.evaluator import Evaluator

    engine = create_engine(str(settings.database_url))
    source = await settings_source(settings, engine)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    store = file_store(settings)
    evaluator = Evaluator(create_sessionmaker(engine), settings, source, store)
    try:
        await evaluator.run(stop)
    finally:
        await evaluator.close()
        await store.close()
        if not await bounded_dispose(engine, settings.end_timeout_s):
            logging.shutdown()
            os._exit(1)


def caller_of(settings: Settings, registry: StreamRegistry) -> Caller:
    from yaksha.caller.phone import PhoneCaller

    if settings.public_url is None:
        reason = "phone calls are off: set YAKSHA_PUBLIC_URL to the address Plivo can reach"
        logging.warning(reason)
        return UnavailableCaller(reason)
    return PhoneCaller(settings, registry)


def plivo_auth_token(source: SettingsSource) -> str | None:
    """The token Plivo signs its requests with, from the settings as last read."""
    latest = source.latest
    credentials = None if latest is None else latest.plivo_credentials
    return None if credentials is None else credentials[1]


async def run_worker(settings: Settings, caller: Caller, registry: StreamRegistry) -> None:
    engine = create_engine(str(settings.database_url))
    sessionmaker = create_sessionmaker(engine)
    source = await settings_source(settings, engine)
    store = file_store(settings)
    worker = Worker(
        sessionmaker,
        caller,
        settings,
        source,
        PhoneAccount(sessionmaker, settings),
        store,
    )
    server = PlivoServer(
        create_app(
            registry, settings.public_url, partial(plivo_auth_token, source), worker.accept_incoming
        ),
        settings.port or 8770,
    )
    await server.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await worker.run(stop)
    finally:
        await server.stop(settings.end_timeout_s)
        await store.close()
        if worker.fatal.is_set() or not await bounded_dispose(engine, settings.end_timeout_s):
            # A leaked task would keep asyncio.run's teardown waiting forever.
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
