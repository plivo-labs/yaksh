# Truman

Simulate, evaluate and improve AI agents. One Python service plus a React frontend.

## Layout

```
src/truman/
  config.py     process settings from environment variables
  domain/       shared data models and interfaces
  caller/       runs the simulated caller and connects to the customer's agent
  simulation/   defines scenarios and personas and orchestrates test conversations
  evaluation/   runs judges and computes scores
  api/          HTTP endpoints for the UI and integrations
  worker/       background jobs
  db/           database models and migrations
frontend/       React UI
docker/         container builds and self-hosted deployment
docs/           Markdown now, Fumadocs site later
tests/          automated tests and fixtures
```

## How a run flows

`api/` accepts a run and queues it. `worker/` claims it and calls `simulation/`. `simulation/` turns each scenario and persona into a prompt and a goal, calls `caller/` once per repeat, and hands every transcript to `evaluation/`. `caller/` has one conversation at a time: dials, talks until the persona hangs up or a cap hits, returns transcript, recording and timing. `evaluation/` scores one transcript per judge and aggregates across repeats. Results go through `db/` and back out through `api/`.

## Rules

- `domain/` imports nothing from the other packages. `simulation/` and `evaluation/` depend on the interfaces in `domain/`, never on `caller/`.
- Business logic lives in `simulation/` and `evaluation/`; `worker/` and `api/` only call it.
- The database is the store; files are the interchange format for scenarios, personas and rubrics.
- Default prompts and starter personas ship inside the package. User edits live in the database and are never overwritten by upgrades.
- Process settings come from environment variables via `config.py`; per-record choices (voice, model) are fields on the record. Secrets exist only in the environment.
- Runtime output goes to configurable storage, default `data/`, gitignored.

## Conventions

- Work on `dev`; `main` is for releases.
- Commit messages follow commitlint: conventional commits, one line, no trailers.
- US English, no em dashes.
