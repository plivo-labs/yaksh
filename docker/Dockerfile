# syntax=docker/dockerfile:1

FROM oven/bun:1.3.9-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

FROM python:3.14-slim-trixie AS backend
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM backend AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH="/app/.venv/bin:$PATH" YAKSHA_API_HOST=0.0.0.0
CMD ["yaksha-server", "api", "--reload"]

FROM python:3.14-slim-trixie
RUN groupadd --system yaksha && useradd --system --gid yaksha --home-dir /app yaksha
WORKDIR /app
COPY --from=backend --chown=yaksha:yaksha /app/.venv ./.venv
COPY --from=frontend --chown=yaksha:yaksha /build/dist ./frontend/dist
ENV PATH="/app/.venv/bin:$PATH" \
    YAKSHA_API_HOST=0.0.0.0 \
    YAKSHA_FRONTEND_DIST=/app/frontend/dist
USER yaksha
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT:-8000}/api/v1/health')"
CMD ["yaksha-server", "api"]
