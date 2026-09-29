import asyncio
import logging
import os
import signal

import typer
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from uvicorn.config import LOGGING_CONFIG

from truman.caller.plivo_server import PlivoServer, StreamRegistry, create_app
from truman.caller.unavailable import UnavailableCaller
from truman.config import Settings
from truman.db.migrate import upgrade_to_head
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import Caller
from truman.integrations.plivo import PlivoApi, PlivoError
from truman.simulation import conversations
from truman.worker.worker import Worker

cli = typer.Typer(no_args_is_help=True, add_completion=False)

API_LOGGING = {
    **LOGGING_CONFIG,
    "loggers": {
        **LOGGING_CONFIG["loggers"],
        "truman": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}


@cli.callback()
def main_callback() -> None:
    pass


@cli.command()
def api(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    settings = Settings()
    uvicorn.run(
        "truman.api:create_app",
        factory=True,
        host=host or settings.api_host,
        port=port or settings.api_port,
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
    api = plivo_api(settings)
    caller = callers(settings, registry, api)
    try:
        asyncio.run(run_worker(settings, caller, registry, api))
    except conversations.UnknownNumbersError as error:
        logging.critical("TRUMAN_PLIVO_NUMBERS: %s", error)
        raise SystemExit(1) from None


def plivo_api(settings: Settings) -> PlivoApi | None:
    if settings.plivo_auth_id is None or settings.plivo_auth_token is None:
        return None
    return PlivoApi(
        settings.plivo_auth_id.get_secret_value(), settings.plivo_auth_token.get_secret_value()
    )


def callers(settings: Settings, registry: StreamRegistry, api: PlivoApi | None) -> Caller:
    from truman.caller.phone import PhoneCaller

    if api is None:
        reason = "phone calls are off: set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN"
    elif settings.public_url is None:
        reason = "phone calls are off: set TRUMAN_PUBLIC_URL to the address Plivo can reach"
    else:
        return PhoneCaller(settings, registry, api)
    logging.warning(reason)
    return UnavailableCaller(reason)


async def sync_pool(
    sessionmaker: async_sessionmaker[AsyncSession], api: PlivoApi, allowlist: list[str]
) -> None:
    """Refresh the number pool from the account; when Plivo cannot be reached, the last synced
    pool stands."""
    try:
        numbers = await api.list_numbers()
    except PlivoError as error:
        logging.warning("keeping the last synced number pool: %s", error)
        return
    if not numbers:
        logging.warning("keeping the last synced number pool: the account listed no numbers")
        return
    async with sessionmaker() as session:
        enabled = await conversations.sync_numbers(session, numbers, allowlist)
    logging.info(
        "number pool: %d of %d account numbers enabled: %s",
        len(enabled),
        len(numbers),
        ", ".join(enabled[:10]) + (", ..." if len(enabled) > 10 else ""),
    )


async def run_worker(
    settings: Settings, caller: Caller, registry: StreamRegistry, api: PlivoApi | None
) -> None:
    engine = create_engine(str(settings.database_url))
    sessionmaker = create_sessionmaker(engine)
    if api is not None:
        await sync_pool(sessionmaker, api, settings.plivo_numbers)
    worker = Worker(sessionmaker, caller, settings)
    server = None
    if settings.public_url and api is not None:
        server = PlivoServer(
            create_app(registry, settings.public_url, api.auth_token), settings.stream_port
        )
        await server.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await worker.run(stop)
    finally:
        if server is not None:
            await server.stop(settings.end_timeout_s)
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
