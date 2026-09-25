import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, status

from truman import __version__
from truman.api.errors import register_error_handlers
from truman.api.routes import agents, conversations, health, personas, voices
from truman.config import Settings
from truman.db.migrate import upgrade_to_head
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.personas import VoiceProvider
from truman.integrations.elevenlabs import ElevenLabsCatalog
from truman.simulation.personas import VoiceCatalogs, seed_builtin_personas

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings
    await asyncio.to_thread(upgrade_to_head, str(settings.database_url))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(settings.data_dir, os.W_OK):
        raise RuntimeError(f"data directory is not writable: {settings.data_dir}")
    async with app.state.sessionmaker() as session:
        seeded = await seed_builtin_personas(session)
    if seeded:
        log.info("seeded built-in personas: %s", ", ".join(seeded))
    yield
    await app.state.engine.dispose()


def voice_catalogs(settings: Settings) -> VoiceCatalogs:
    if settings.elevenlabs_api_key is None:
        return {}
    return {
        VoiceProvider.ELEVENLABS: ElevenLabsCatalog(settings.elevenlabs_api_key.get_secret_value())
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Truman", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_engine(str(settings.database_url))
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.voice_catalogs = voice_catalogs(settings)
    register_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(health.router)
    api.include_router(agents.router)
    api.include_router(conversations.router)
    api.include_router(personas.router)
    api.include_router(voices.router)
    app.include_router(api)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/{path:path}", include_in_schema=False)
    async def unknown_api_route(path: str = "") -> None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such route")

    if (settings.frontend_dist / "index.html").is_file():
        app.frontend("/", directory=settings.frontend_dist)
    return app
