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

## Phone

Agents with `transport: phone` are called on the real phone network through [Plivo](https://www.plivo.com): the worker dials the agent's number from one of your Plivo numbers, receives the call audio over a Plivo stream and hangs up through the API. Plivo has to reach the worker, so it needs a public HTTPS address.

| Variable | Purpose |
| --- | --- |
| `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN` | The Plivo account that owns the numbers and places the calls. |
| `TRUMAN_PLIVO_NUMBERS` | Comma-separated E.164 numbers on that account to call from. Each running phone conversation takes one, so the pool bounds phone concurrency. |
| `TRUMAN_PUBLIC_URL` | The public `https://` address that reaches the worker's port 8770. Phone calls are off without it. |
| `TRUMAN_RING_TIMEOUT_S` | How long the agent's number rings before the call ends as `no_answer`, default 30. |

For development, `scripts/tunnel.sh` opens a Cloudflare quick tunnel to the worker (no account needed) and prints the `TRUMAN_PUBLIC_URL` line to put in `docker/.env`; the hostname changes every time the tunnel starts. For a fixed hostname, run a [named tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) that routes your hostname to `http://worker:8770`, or put the worker behind any other public HTTPS host. Either way, the worker reads `TRUMAN_PUBLIC_URL` at startup, so recreate it after changing the value:

```sh
docker compose -f docker/compose.dev.yaml create --force-recreate worker
docker compose -f docker/compose.dev.yaml start worker
```

Create the agent with its number, then start a conversation; the wire events show `ringing`, `answered` and `connected` as the call progresses:

```sh
curl -X POST localhost:8000/api/v1/agents -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Support line", "transport": "phone", "agent_number": "+14155550100"}'
curl -X POST localhost:8000/api/v1/conversations -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"agent_id": "<id from the previous call>", "persona_prompt": "You want to book a table for two tonight."}'
```

## Develop

```sh
docker compose -f docker/compose.dev.yaml up --build
```

Open http://localhost:5173. Python and frontend changes reload in place.

Without Docker: `uv sync && uv run prek install`, start Postgres (`docker compose -f docker/compose.dev.yaml up postgres`), export `TRUMAN_API_TOKEN` and `TRUMAN_DATABASE_URL=postgresql+asyncpg://truman:truman@localhost:5433/truman`, then `uv run truman api --reload`, `uv run truman worker` in a second terminal, and, in `frontend/`, `bun install && bun run dev`. Tests start their own Postgres through Docker.
