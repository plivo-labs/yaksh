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
| `ELEVENLABS_API_KEY` | Text to speech. The API needs it too, to look up a voice when you add it and to play previews. Each persona picks its own voice from the voices list. |
| `OPENAI_API_KEY`, or `AZURE_OPENAI_ENDPOINT` with `AZURE_OPENAI_API_KEY` (and `AZURE_OPENAI_API_VERSION`) | The persona model. `TRUMAN_PERSONA_MODEL` names the model or the Azure deployment, default `gpt-4.1`. |
| `TRUMAN_TIMEZONE` | The IANA timezone that sets the caller's "today" when a conversation is created, default `UTC`. |

## Phone

Agents are called on the real phone network through [Plivo](https://www.plivo.com): the worker dials the agent's number from one of your Plivo numbers, receives the call audio over a Plivo stream and hangs up through the API. Plivo has to reach the worker, so it needs a public HTTPS address; until these settings are in place, conversations cannot be started.

| Variable | Purpose |
| --- | --- |
| `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN` | The Plivo account that owns the numbers and places the calls. |
| `TRUMAN_PLIVO_NUMBERS` | Optional. By default the worker calls from every voice-capable number on the account; set a comma-separated E.164 list to use only those. Each running phone conversation takes one number, so the pool bounds phone concurrency. |
| `TRUMAN_PUBLIC_URL` | The public `https://` address that reaches the worker's port 8770. Phone calls are off without it. |
| `TRUMAN_RING_TIMEOUT_S` | How long the agent's number rings before the call ends as `no_answer`, default 30. |

For development, `scripts/tunnel.sh` opens a Cloudflare quick tunnel to the worker (no account needed) and prints the `TRUMAN_PUBLIC_URL` line to put in `docker/.env`; the hostname changes every time the tunnel starts. For a fixed hostname, run a [named tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) that routes your hostname to `http://worker:8770`, or put the worker behind any other public HTTPS host. Either way, the worker reads `TRUMAN_PUBLIC_URL` at startup, so recreate it after changing the value:

```sh
docker compose -f docker/compose.dev.yaml create --force-recreate worker
docker compose -f docker/compose.dev.yaml start worker
```

Create the agent with its number and a scenario for it, then start a conversation with the scenario and a persona. `GET /api/v1/personas` lists the built-in personas. The wire events show `ringing`, `answered` and `connected` as the call progresses:

```sh
curl -X POST localhost:8000/api/v1/agents -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Support line", "agent_number": "+14155550100"}'
curl -X POST localhost:8000/api/v1/agents/<agent id>/scenarios -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Book a table", "goal": "Book a table for two tonight.", "known_facts": [{"name": "Name", "value": "Priya Raman"}], "criteria": ["Reads the time and party size back before it books."]}'
curl -X POST localhost:8000/api/v1/conversations -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"agent_id": "<agent id>", "scenario_id": "<scenario id>", "persona_id": "<persona id>"}'
```

## Files

Uploaded files (PDF, TXT and MD documents about an agent) are kept in S3-compatible storage. The compose files run [SeaweedFS](https://github.com/seaweedfs/seaweedfs) for this, with its data in the `storage` volume. To use S3, R2 or another S3-compatible service instead, set:

| Variable | Purpose |
| --- | --- |
| `TRUMAN_S3_ENDPOINT` | The storage URL. File uploads are off without it; pasted text still works. |
| `TRUMAN_S3_BUCKET` | The bucket, default `truman`. It must exist. |
| `TRUMAN_S3_ACCESS_KEY`, `TRUMAN_S3_SECRET_KEY` | The credentials. |
| `TRUMAN_S3_REGION` | Default `us-east-1`. |

## Outbound agents

An outbound agent calls Truman. Truman sends the agent's trigger, a POST request that makes the agent call one of Truman's numbers, and answers that call.

1. In the Plivo console, create an Application with answer URL `<TRUMAN_PUBLIC_URL>/incoming` and hangup URL `<TRUMAN_PUBLIC_URL>/incoming/hangup`, both `POST`, and link the numbers that receive test calls to it.
2. Set the variables below and restart the worker. It reads the Application and its numbers at startup. The Numbers page says why outbound tests are off, if they are.
3. Create an agent with direction outbound, its trigger URL, headers and JSON body. In the trigger, `{{truman.number}}` is the number to call, `{{truman.conversation_id}}` the conversation, `{{agent_data.<name>}}` a value from the scenario and `{{env.TRUMAN_TRIGGER_<NAME>}}` a secret from the environment.

| Variable | Purpose |
| --- | --- |
| `TRUMAN_PLIVO_APP_ID` | The Application from step 1. Outbound tests are off without it. |
| `TRUMAN_TRIGGER_<NAME>` | Secrets for triggers, such as API keys. |
| `TRUMAN_WEBHOOK_SIGNING_KEY` | Optional. Signs each trigger with `X-Truman-Signature` (HMAC-SHA256 over `<X-Truman-Delivery>.<X-Truman-Timestamp>.<body>`). See `docs/decisions/0004-signed-triggers.md`. |
| `TRUMAN_ALLOW_PRIVATE_TRIGGERS` | Optional. Allows `http` and private addresses as trigger URLs, for agents on your own network. Default off. |
| `TRUMAN_NUMBER_REST_S` | How long a number rests after a test before it receives another outbound call, default 300. |

## Develop

```sh
docker compose -f docker/compose.dev.yaml up --build
```

Open http://localhost:5173. Python and frontend changes reload in place.

Without Docker: `uv sync && uv run prek install`, start Postgres (`docker compose -f docker/compose.dev.yaml up postgres`), export `TRUMAN_API_TOKEN` and `TRUMAN_DATABASE_URL=postgresql+asyncpg://truman:truman@localhost:5433/truman`, then `uv run truman api --reload`, `uv run truman worker` in a second terminal, and, in `frontend/`, `bun install && bun run dev`. Tests start their own Postgres through Docker.
