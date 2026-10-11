import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, status

from yaksha import __version__
from yaksha.api.body_limit import BodySizeLimit
from yaksha.api.errors import CLIENT_ERRORS, register_error_handlers
from yaksha.api.generations import Generations
from yaksha.api.providers import Providers
from yaksha.api.routes import (
    agents,
    conversations,
    defaults,
    documents,
    health,
    judges,
    labelers,
    personas,
    phone_numbers,
    review,
    runs,
    scenarios,
    sounds,
    voices,
)
from yaksha.api.routes import (
    settings as settings_routes,
)
from yaksha.config import Settings
from yaksha.db.migrate import upgrade_to_head
from yaksha.db.session import create_engine, create_sessionmaker
from yaksha.domain.documents import MAX_FILE_BYTES
from yaksha.settings.cipher import Cipher, SecretUnreadableError
from yaksha.settings.store import SettingsSource
from yaksha.simulation.generation import stop_running
from yaksha.simulation.personas import seed_builtin_personas
from yaksha.simulation.voices import seed_builtin_voices
from yaksha.storage import file_store

log = logging.getLogger(__name__)

MAX_REQUEST_BYTES = MAX_FILE_BYTES + 1024 * 1024
"""The largest upload plus room for the multipart framing."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings
    await asyncio.to_thread(upgrade_to_head, str(settings.database_url))
    try:
        await app.state.source.current()
    except SecretUnreadableError as error:
        raise RuntimeError(f"cannot read the stored settings: {error}") from None
    async with app.state.sessionmaker() as session:
        voices = await seed_builtin_voices(session)
        personas = await seed_builtin_personas(session)
        await stop_running(session)
    if voices:
        log.info("seeded built-in voices: %s", ", ".join(voices))
    if personas:
        log.info("seeded built-in personas: %s", ", ".join(personas))
    yield
    await app.state.generations.close()
    await app.state.providers.close()
    await app.state.file_store.close()
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Yaksha", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_engine(str(settings.database_url))
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.source = SettingsSource(
        app.state.sessionmaker, Cipher(settings.encryption_key.get_secret_value())
    )
    app.state.providers = Providers()
    app.state.generations = Generations(app.state.sessionmaker)
    app.state.file_store = file_store(settings)
    register_error_handlers(app)
    app.add_middleware(BodySizeLimit, max_bytes=MAX_REQUEST_BYTES)

    api = APIRouter(prefix="/api/v1", responses=CLIENT_ERRORS)
    api.include_router(health.router)
    api.include_router(agents.router)
    api.include_router(conversations.router)
    api.include_router(defaults.router)
    api.include_router(documents.router)
    api.include_router(judges.router)
    api.include_router(labelers.router)
    api.include_router(personas.router)
    api.include_router(phone_numbers.router)
    api.include_router(review.router)
    api.include_router(runs.router)
    api.include_router(scenarios.router)
    api.include_router(settings_routes.router)
    api.include_router(sounds.router)
    api.include_router(voices.router)
    app.include_router(api)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/{path:path}", include_in_schema=False)
    async def unknown_api_route(path: str = "") -> None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such route")

    if (settings.frontend_dist / "index.html").is_file():
        app.frontend("/", directory=settings.frontend_dist)
    return app
