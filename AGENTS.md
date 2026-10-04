# Truman

Simulate, evaluate and improve AI agents. One Python service plus a React frontend.

Truman is open source and self-hosted: users run it on their own infrastructure. Plivo builds it and provides the phone network, but Plivo does not run it as a service. Design for outside users, not for Plivo-internal infrastructure.

## Layout

```
src/truman/
  config.py     process settings from environment variables
  domain/       shared data models and interfaces
  caller/       runs the simulated caller and connects to the customer's agent
  integrations/ clients for outside services: Plivo, ElevenLabs
  simulation/   defines scenarios and personas and orchestrates test conversations
  evaluation/   runs judges and computes scores (planned, empty today)
  api/          HTTP endpoints for the UI and integrations
  worker/       claims queued conversations from Postgres and runs them under a lease
  db/           database models and migrations
frontend/       React UI
cli/            Go command-line client for the API, its own module; skill/SKILL.md is the guide for coding agents
docker/         container builds and self-hosted deployment
docs/           docs site (Fumadocs, pages in docs/content/docs/); decisions, ideas and bugs as Markdown
tests/          automated tests and fixtures
```

## How a test flows

Two stages, each a separate job, each retryable on its own. Today the simulated test runs up to the saved conversation; the evaluation stage and imported calls are planned.

```
Simulated test:   api -> worker -> simulation -> caller -> saved conversation
                                -> evaluation -> saved results
Imported call:    api -> worker -> evaluation -> saved results
```

`simulation/` turns each scenario and persona into a prompt and a goal and calls the `Caller` interface once per conversation. A run creates one conversation for each repeat of each scenario; a retry is a new conversation (attempt + 1, `retry_of`) that copies the inputs of the one it replaces (docs/decisions/0012). `caller/` has one conversation at a time and returns transcript, recording and timing; the conversation is saved before anything is judged. `evaluation/` starts from a saved conversation, whoever produced it: one result per conversation per judge, then reliability (pass@k, pass^k) across repeats. Only the latest attempt of each repeat of each scenario counts: a conversation that another one's `retry_of` points to is not a sample. `worker/` only sequences the stages. A conversation freezes its inputs when it is created: the pinned agent, scenario and persona versions and the finished caller prompt; how the caller maps them to provider settings follows the running code. A run creates its conversations at once with the same versions and the same "today"; a retry keeps the prompt, and so the "today", of the attempt it replaces. With evaluation, a run will also freeze its rubric and judge prompt versions.

## Rules

- `domain/` imports nothing from the other packages. `simulation/` and `evaluation/` depend on the interfaces in `domain/`, never on `caller/`.
- Business logic lives in `simulation/` and `evaluation/`; `worker/` and `api/` only call it. Evaluation never depends on simulation; evaluator execution errors may retry evaluation, never the call. A valid failing verdict or low score is a result, not a retryable error.
- The database is the store; files are the interchange format for scenarios, personas and rubrics.
- Default prompts and starter personas ship inside the package. User edits live in the database and are never overwritten by upgrades.
- Process settings come from environment variables via `config.py`; per-record choices (voice, model) are fields on the record. Secrets exist only in the environment.
- Runtime output goes to configurable storage, default `data/`, gitignored.
- Locks are taken in one order: an agent, then its scenarios, then personas, each set in id order; a run before its conversations; a conversation before phone numbers. Starting conversations share-locks the scenarios and personas, so transactions that only reference them do not wait.
- A time that is written or compared after a possible lock wait uses `statement_timestamp()`. Creation times keep `now()`, the time of the transaction, so the rows one transaction creates share one time.

## Conventions

- Modern, battle-tested tooling and libraries, current stable versions: Python 3.14 with uv, ruff, pyrefly, pytest; FastAPI, SQLAlchemy 2, Alembic, Pydantic 2. No legacy tools kept for familiarity.
- The import rules above are enforced by import-linter (`lint-imports`, contracts in `pyproject.toml`).
- The CLI is Go with cobra; its API client is generated with oapi-codegen from `cli/openapi.json`. After an API change, run `uv run python scripts/export_openapi.py` and `go -C cli generate ./...`; CI fails when the spec or the client is out of date.
- Records that a conversation depends on are versioned: every change to an agent's configuration writes an `agent_versions` row, and a conversation pins the version it ran against.
- Work on `dev`; `main` is for releases.
- Commit messages follow commitlint: conventional commits, one line, no trailers.
- US English, no em dashes.
