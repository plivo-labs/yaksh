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

Two stages, each a separate job, each retryable on its own.

```
Simulated test:   api -> worker -> simulation -> caller -> saved conversation
                                -> evaluation -> saved results
Imported call:    api -> worker -> evaluation -> saved results
```

`simulation/` turns each scenario and persona into a prompt and a goal and calls `caller/` once per repeat; `caller/` has one conversation at a time and returns transcript, recording and timing; the conversation is saved before anything is judged. `evaluation/` starts from a saved conversation, whoever produced it: one result per conversation per judge, then reliability (pass@k, pass^k) across repeats. `worker/` only sequences the stages. A run freezes its inputs: scenario, persona, rubric, judge prompt versions and resolved settings.

## Rules

- `domain/` imports nothing from the other packages. `simulation/` and `evaluation/` depend on the interfaces in `domain/`, never on `caller/`.
- Business logic lives in `simulation/` and `evaluation/`; `worker/` and `api/` only call it. Evaluation never depends on simulation; a judge failure re-runs evaluation, never the call.
- The database is the store; files are the interchange format for scenarios, personas and rubrics.
- Default prompts and starter personas ship inside the package. User edits live in the database and are never overwritten by upgrades.
- Process settings come from environment variables via `config.py`; per-record choices (voice, model) are fields on the record. Secrets exist only in the environment.
- Runtime output goes to configurable storage, default `data/`, gitignored.

## Conventions

- Work on `dev`; `main` is for releases.
- Commit messages follow commitlint: conventional commits, one line, no trailers.
- US English, no em dashes.
