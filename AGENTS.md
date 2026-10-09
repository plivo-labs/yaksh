# Yaksha

Simulate, evaluate and improve AI agents. One Python service plus a React frontend.

Yaksha is open source and self-hosted: users run it on their own infrastructure. Plivo builds it and provides the phone network, but Plivo does not run it as a service. Design for outside users, not for Plivo-internal infrastructure.

## Layout

```
src/yaksha/
  config.py     what a process needs to start, from environment variables
  settings/     the Settings page's settings: one database row, its secrets encrypted, read again when its version changes
  domain/       shared data models and interfaces
  caller/       runs the simulated caller and connects to the customer's agent
  integrations/ clients for outside services: Plivo, ElevenLabs
  simulation/   defines scenarios and personas and orchestrates test conversations
  evaluation/   the evaluation queue, and the metrics, judges and labels of saved conversations
  api/          HTTP endpoints for the UI and integrations
  worker/       claims queued conversations from Postgres and runs them under a lease; evaluator.py does the same for evaluations
  db/           database models and migrations
frontend/       React UI
cli/            Go command-line client for the API, its own module; skill/yaksha/SKILL.md is the guide for coding agents
docker/         container builds and self-hosted deployment
docs/           docs site (Fumadocs, pages in docs/content/docs/); decisions, ideas and bugs as Markdown
tests/          automated tests and fixtures
```

## How a test flows

Two stages, each a separate job, each retryable on its own. The worker saves the conversation and queues its evaluation in the same transaction; the evaluator service claims the evaluation under a lease and stores the metrics (docs/decisions/0022). Imported calls are planned.

```
Simulated test:   api -> worker -> simulation -> caller -> saved conversation, queued evaluation
                  evaluator -> evaluation -> saved metrics and verdicts
Imported call:    api -> queued evaluation -> evaluator -> evaluation -> saved metrics and verdicts
```

`simulation/` turns each scenario and persona into the caller's prompt (the persona, the scenario's instructions and facts) and calls the `Caller` interface once per conversation. A run creates one conversation for each repeat of each scenario; a retry is a new conversation (attempt + 1, `retry_of`) that copies the inputs of the one it replaces (docs/decisions/0012). `caller/` has one conversation at a time and returns transcript, recording and timing; the conversation is saved before anything is judged. `evaluation/` starts from a saved conversation, whoever produced it: one result per conversation per judge, then reliability (pass@k, pass^k) across repeats. Only the latest attempt of each repeat of each scenario counts: a conversation that another one's `retry_of` points to is not a sample. `worker/` only sequences the stages. A conversation freezes its inputs when it is created: the pinned agent, scenario and persona versions and the finished caller prompt; how the caller maps them to provider settings follows the running code. A run creates its conversations at once with the same versions and the same "today"; a retry keeps the prompt, and so the "today", of the attempt it replaces. With evaluation, a run will also freeze its rubric and judge prompt versions.

## Rules

- `domain/` imports nothing from the other packages. `simulation/` and `evaluation/` depend on the interfaces in `domain/`, never on `caller/`.
- Business logic lives in `simulation/` and `evaluation/`; `worker/` and `api/` only call it. Evaluation never depends on simulation; evaluator execution errors may retry evaluation, never the call. A valid failing verdict or low score is a result, not a retryable error.
- The database is the store; files are the interchange format for scenarios, personas and rubrics.
- Default prompts and starter personas ship inside the package. User edits live in the database and are never overwritten by upgrades.
- What a process needs to start comes from environment variables via `config.py`. Every other setting is on the Settings page: `domain/settings.py` defines it with its default, and `settings/store.py` keeps the values that differ from the defaults in the `app_settings` row. A process reads that row again when its version changes, and a call carries the settings it started with. Per-record choices (voice, model) are fields on the record.
- Secrets are encrypted in the `app_settings` row with AES-256-GCM under `YAKSHA_ENCRYPTION_KEY`. The API never returns one. See `docs/decisions/0027-settings-in-the-database.md`.
- Uploaded documents and call audio go to the S3-compatible file storage. No process writes local files. See `docs/decisions/0028-call-audio-in-file-storage.md`.
- Locks are taken in one order: an agent, then its scenarios, then personas, each set in id order; a run before its conversations; a conversation before phone numbers; an evaluation before its items. Starting conversations share-locks the scenarios and personas, so transactions that only reference them do not wait.
- A time that is written or compared after a possible lock wait uses `statement_timestamp()`. Creation times keep `now()`, the time of the transaction, so the rows one transaction creates share one time.

## Conventions

- Modern, battle-tested tooling and libraries, current stable versions: Python 3.14 with uv, ruff, pyrefly, pytest; FastAPI, SQLAlchemy 2, Alembic, Pydantic 2. No legacy tools kept for familiarity.
- The import rules above are enforced by import-linter (`lint-imports`, contracts in `pyproject.toml`).
- The CLI is Go with cobra; its API client is generated with oapi-codegen from `cli/openapi.json`. After an API change, run `uv run python scripts/export_openapi.py` and `go -C cli generate ./...`; CI fails when the spec or the client is out of date.
- The console's colors, type ramp and radius come from `@plivo/tokens` (pinned in `frontend/package.json`), and its `DESIGN.md` is the style guide. Use the token classes, such as `text-p-400`, `bg-bg1` and the tag pairs, and not Tailwind's default text sizes or a literal color. The token classes take no variant prefix: choose them in TSX. Indigo (`brand`) never colors a control.
- Records that a conversation depends on are versioned: every change to an agent's configuration writes an `agent_versions` row, and a conversation pins the version it ran against.
- Work on `dev`; `main` is for releases.
- Commit messages follow commitlint: conventional commits, one line, no trailers.
- US English, no em dashes.
