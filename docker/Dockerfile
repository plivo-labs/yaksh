FROM oven/bun:1.3.9-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

FROM python:3.14-slim-trixie AS backend
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM backend AS dev
RUN uv sync --locked
ENV PATH="/app/.venv/bin:$PATH" YAKSH_API_HOST=0.0.0.0
CMD ["yaksh-server", "api", "--reload"]

FROM python:3.14-slim-trixie
RUN groupadd --system yaksh && useradd --system --gid yaksh --home-dir /app yaksh
WORKDIR /app
COPY --from=backend --chown=yaksh:yaksh /app/.venv ./.venv
COPY --from=frontend --chown=yaksh:yaksh /build/dist ./frontend/dist
ENV PATH="/app/.venv/bin:$PATH" \
    YAKSH_API_HOST=0.0.0.0 \
    YAKSH_FRONTEND_DIST=/app/frontend/dist
USER yaksh
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT:-8000}/api/v1/health')"
CMD ["yaksh-server", "api"]
