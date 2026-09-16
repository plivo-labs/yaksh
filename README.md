# Truman

Simulate, evaluate and improve AI agents. Open source, runs on your own infrastructure. Fully customizable, with the best defaults. By [Plivo](https://plivo.com).

## Run

```sh
cp docker/.env.example docker/.env   # set TRUMAN_API_TOKEN
docker compose -f docker/compose.yaml up --build
```

Open http://localhost:8000. The API is under `/api/v1` and takes the token as a bearer header.

## Caller

The worker phones agents with a [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline: Deepgram hears the agent, an OpenAI model plays the persona, ElevenLabs speaks. Put the keys in `docker/.env` (or the environment):

| Variable | Purpose |
| --- | --- |
| `DEEPGRAM_API_KEY` | Speech to text. `TRUMAN_DEEPGRAM_URL` points at a self-hosted Deepgram; empty means Deepgram cloud. |
| `ELEVENLABS_API_KEY` | Text to speech. `TRUMAN_ELEVENLABS_VOICE_ID` picks the voice. |
| `OPENAI_API_KEY`, or `AZURE_OPENAI_ENDPOINT` with `AZURE_OPENAI_API_KEY` (and `AZURE_OPENAI_API_VERSION`) | The persona model. `TRUMAN_PERSONA_MODEL` names the model or the Azure deployment, default `gpt-4.1`. |

An agent's `upgrade_headers` and `extra_headers` may hold `env:NAME` values; the worker reads `NAME` from its environment when it connects, so secrets never reach the database. `TRUMAN_CALLER=stub` runs the worker with a canned caller and no providers, which is enough to develop the API and the UI.

## Develop

```sh
docker compose -f docker/compose.dev.yaml up --build
```

Open http://localhost:5173. Python and frontend changes reload in place.

Without Docker: `uv sync && uv run prek install`, start Postgres (`docker compose -f docker/compose.dev.yaml up postgres`), export `TRUMAN_API_TOKEN` and `TRUMAN_DATABASE_URL=postgresql+asyncpg://truman:truman@localhost:5433/truman`, then `uv run truman api --reload`, `uv run truman worker` in a second terminal, and, in `frontend/`, `bun install && bun run dev`. Tests start their own Postgres through Docker.
