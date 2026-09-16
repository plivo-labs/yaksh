# Truman

Simulate, evaluate and improve AI agents. Open source, runs on your own infrastructure. Fully customizable, with the best defaults. By [Plivo](https://plivo.com).

## Run

```sh
cp docker/.env.example docker/.env   # set TRUMAN_API_TOKEN
docker compose -f docker/compose.yaml up --build
```

Open http://localhost:8000. The API is under `/api/v1` and takes the token as a bearer header.

## Develop

```sh
docker compose -f docker/compose.dev.yaml up --build
```

Open http://localhost:5173. Python and frontend changes reload in place.

Without Docker: `uv sync && uv run prek install`, start Postgres (`docker compose -f docker/compose.dev.yaml up postgres`), export `TRUMAN_API_TOKEN` and `TRUMAN_DATABASE_URL=postgresql+asyncpg://truman:truman@localhost:5433/truman`, then `uv run truman api --reload` and, in `frontend/`, `bun install && bun run dev`. Tests start their own Postgres through Docker.
