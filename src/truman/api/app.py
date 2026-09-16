import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, status

from truman import __version__
from truman.api.errors import register_error_handlers
from truman.api.routes import agents, conversations, health
from truman.config import Settings
from truman.db.migrate import upgrade_to_head
from truman.db.session import create_engine, create_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings
    await asyncio.to_thread(upgrade_to_head, str(settings.database_url))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(settings.data_dir, os.W_OK):
        raise RuntimeError(f"data directory is not writable: {settings.data_dir}")
    yield
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Truman", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_engine(str(settings.database_url))
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    register_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(health.router)
    api.include_router(agents.router)
    api.include_router(conversations.router)
    app.include_router(api)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/{path:path}", include_in_schema=False)
    async def unknown_api_route(path: str = "") -> None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such route")

    if (settings.frontend_dist / "index.html").is_file():
        app.frontend("/", directory=settings.frontend_dist)
    return app
