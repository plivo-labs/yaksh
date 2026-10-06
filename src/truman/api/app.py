import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, status

from truman import __version__
from truman.api.body_limit import BodySizeLimit
from truman.api.errors import CLIENT_ERRORS, register_error_handlers
from truman.api.routes import (
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
    voices,
)
from truman.config import Settings
from truman.db.migrate import upgrade_to_head
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.documents import MAX_FILE_BYTES, FileStore
from truman.domain.language_models import JsonModel
from truman.domain.voices import VoiceProvider
from truman.integrations.elevenlabs import ElevenLabsClient
from truman.integrations.openai_models import OpenAIJsonModel
from truman.integrations.s3 import S3FileStore
from truman.simulation.personas import seed_builtin_personas
from truman.simulation.voices import VoiceClients, seed_builtin_voices

log = logging.getLogger(__name__)

MAX_REQUEST_BYTES = MAX_FILE_BYTES + 1024 * 1024
"""The largest upload plus room for the multipart framing."""


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
    if app.state.generation_model is not None:
        await app.state.generation_model.close()
    await app.state.engine.dispose()


def voice_clients(settings: Settings) -> VoiceClients:
    if settings.elevenlabs_api_key is None:
        return {}
    return {
        VoiceProvider.ELEVENLABS: ElevenLabsClient(settings.elevenlabs_api_key.get_secret_value())
    }


def file_store(settings: Settings) -> FileStore | None:
    if (
        settings.s3_endpoint is None
        or settings.s3_access_key is None
        or settings.s3_secret_key is None
    ):
        return None
    return S3FileStore(
        settings.s3_endpoint,
        settings.s3_bucket,
        settings.s3_access_key.get_secret_value(),
        settings.s3_secret_key.get_secret_value(),
        region=settings.s3_region,
    )


def generation_model(settings: Settings) -> JsonModel | None:
    """The OpenAI-compatible API at OPENAI_BASE_URL, as for the caller."""
    model = settings.generation_llm_model or settings.persona_llm_model
    if settings.openai_api_key is None:
        return None
    return OpenAIJsonModel.openai(
        settings.openai_api_key.get_secret_value(),
        model,
        base_url=settings.openai_base_url,
        timeout_s=settings.generation_llm_timeout_s,
        reasoning_effort=settings.generation_llm_reasoning_effort,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Truman", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_engine(str(settings.database_url))
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.voice_clients = voice_clients(settings)
    app.state.file_store = file_store(settings)
    app.state.generation_model = generation_model(settings)
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
    api.include_router(voices.router)
    app.include_router(api)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/{path:path}", include_in_schema=False)
    async def unknown_api_route(path: str = "") -> None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such route")

    if (settings.frontend_dist / "index.html").is_file():
        app.frontend("/", directory=settings.frontend_dist)
    return app
