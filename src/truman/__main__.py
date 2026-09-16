import asyncio
import logging
import os
import signal

import typer
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine

from truman.caller.stub import StubCaller
from truman.config import Settings
from truman.db.migrate import upgrade_to_head
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import Caller
from truman.worker.worker import Worker

cli = typer.Typer(no_args_is_help=True, add_completion=False)


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
    )


@cli.command()
def migrate() -> None:
    upgrade_to_head(str(Settings().database_url))


@cli.command()
def worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    upgrade_to_head(str(settings.database_url))
    asyncio.run(run_worker(settings, StubCaller()))


async def run_worker(settings: Settings, caller: Caller) -> None:
    engine = create_engine(str(settings.database_url))
    worker = Worker(create_sessionmaker(engine), caller, settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await worker.run(stop)
    finally:
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
