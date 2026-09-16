# Truman

Simulate, evaluate and improve AI agents. Open source, runs on your own infrastructure. Fully customizable, with the best defaults. By [Plivo](https://plivo.com).

## Run

```sh
docker compose -f docker/compose.yaml up --build
```

Open http://localhost:8000.

## Develop

```sh
docker compose -f docker/compose.dev.yaml up --build
```

Open http://localhost:5173. Python and frontend changes reload in place.

Without Docker: `uv sync && uv run prek install`, then `uv run truman api --reload` and, in `frontend/`, `bun install && bun run dev`.
