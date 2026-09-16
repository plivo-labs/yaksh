from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from truman import __version__
from truman.api.routes import health
from truman.config import settings


def create_app(frontend_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="Truman", version=__version__)

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    app.include_router(api)

    dist = settings.frontend_dist if frontend_dist is None else frontend_dist
    if (dist / "index.html").is_file():
        mount_frontend(app, dist)
    return app


def mount_frontend(app: FastAPI, dist: Path) -> None:
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (root / path).resolve()
        if path and file.is_relative_to(root) and file.is_file():
            return FileResponse(file)
        return FileResponse(index)
