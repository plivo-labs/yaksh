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
from truman.domain.voices import VoiceProvider
from truman.integrations.elevenlabs import ElevenLabsClient
from truman.simulation.personas import seed_builtin_personas
from truman.simulation.voices import VoiceClients, seed_builtin_voices

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings
    await asyncio.to_thread(upgrade_to_head, str(settings.database_url))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(settings.data_dir, os.W_OK):
        raise RuntimeError(f"data directory is not writable: {settings.data_dir}")
    async with app.state.sessionmaker() as session:
        voices = await seed_builtin_voices(session)
        personas = await seed_builtin_personas(session)
    if voices:
        log.info("seeded built-in voices: %s", ", ".join(voices))
    if personas:
        log.info("seeded built-in personas: %s", ", ".join(personas))
    yield
    await app.state.engine.dispose()


def voice_clients(settings: Settings) -> VoiceClients:
    if settings.elevenlabs_api_key is None:
        return {}
    return {
        VoiceProvider.ELEVENLABS: ElevenLabsClient(settings.elevenlabs_api_key.get_secret_value())
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Truman", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_engine(str(settings.database_url))
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.voice_clients = voice_clients(settings)
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
