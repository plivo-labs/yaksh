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
| `DEEPGRAM_API_KEY` | Speech to text. `DEEPGRAM_BASE_URL` points at another Deepgram host, such as a self-hosted one; default `https://api.deepgram.com`. |
| `ELEVENLABS_API_KEY` | Text to speech. The API needs it too, to look up a voice when you add it and to play previews. Each persona picks its own voice from the voices list. |
| `OPENAI_API_KEY` | The persona model. `OPENAI_BASE_URL` points at any API with OpenAI's Responses endpoint, such as an Azure OpenAI resource at `https://<resource>.openai.azure.com/openai/v1/`; default `https://api.openai.com/v1`. `PERSONA_LLM_MODEL` names the model (for Azure, the deployment, named after its model), default `gpt-4.1`; a reasoning model that accepts it gets reasoning effort `none`, so the caller answers fast. `GENERATION_LLM_MODEL` names the model that writes scenarios, default the persona model. |
| `PERSONA_LLM_REASONING_EFFORT` | Optional. The reasoning effort of every caller turn, such as `low`. Unset, a reasoning model that accepts `none` is asked for it, for the fastest answer, and other models get no effort. A model without reasoning refuses any value, so leave it unset for gpt-4.1. |
| `GENERATION_LLM_REASONING_EFFORT` | The reasoning effort of scenario generation, default `max`. Sent only when the model takes it. |
| `GENERATION_LLM_TIMEOUT_S` | The longest one model request may take while writing scenarios, default 300. A request that times out or fails on the provider's side is sent once more. At `xhigh` one scenario takes about 90 seconds. |
| `TRUMAN_TIMEZONE` | The IANA timezone that sets the caller's "today" when a conversation or its run is created, default `UTC`. A retry keeps the "today" of the attempt it replaces. |

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

Pick a persona, create the agent with its number and a scenario that runs with the persona, then start a conversation with the scenario. `GET /api/v1/personas` lists the built-in personas. A conversation uses the scenario's persona; `persona_id` on the conversation picks another one for that call. The wire events show `ringing`, `answered` and `connected` as the call progresses:

```sh
curl localhost:8000/api/v1/personas -H "Authorization: Bearer $TRUMAN_API_TOKEN"
curl -X POST localhost:8000/api/v1/agents -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Support line", "agent_number": "+14155550100"}'
curl -X POST localhost:8000/api/v1/agents/<agent id>/scenarios -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Book a table", "persona_id": "<persona id>", "goal": "Book a table for two tonight.", "known_facts": [{"name": "Name", "value": "Priya Raman"}], "criteria": ["Reads the time and party size back before it books."]}'
curl -X POST localhost:8000/api/v1/conversations -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"agent_id": "<agent id>", "scenario_id": "<scenario id>"}'
```

## Background noise

A persona can have background noise: street, cafe, office, car, TV, crowd, kitchen or wind, at a light, busy or loud level. At these levels the caller's voice is about 20, 10 or 5 dB above the noise. The noise plays for the whole call, also when the caller is silent, and the recording includes it. Truman's own speech to text hears only the agent, so the noise changes only what the agent hears.

`background_noise` on a conversation replaces the persona's setting for that call, for example `{"sound": "none"}` for no noise or `{"sound": "street", "level": "loud"}`. A conversation keeps the setting it started with, and so does its retry. The sound files are loops in `src/truman/simulation/sounds/`; their README says how they were made. See `docs/decisions/0014-background-noise.md`.

## Response time

After each call, Truman measures how long the agent made the caller wait. For each caller reply, the response time runs from the end of the caller's speech to the start of the agent's first speech after it. Before the caller has spoken, it runs from the start of the call's audio, the `connected` wire event, so a slow greeting shows too. When the agent starts before the caller finishes, the reply is a talk-over and has no response time. A reply the agent does not answer before the caller speaks again has no response time either, so the percentiles leave that wait out.

- The end of the caller's speech is when Truman sent the last audio of its reply, the `caller_audio_end` wire event.
- The agent's speech comes from the voice detector of the live call, Pipecat's Silero VAD, run over the agent channel of the recording. A spoken "hmm" counts as speech. In tests, an agent's quiet "thinking" sound did not.
- Truman measures at its own connection, so the number includes the path between Truman and the agent's system, both ways. For a phone call, that is the path to Plivo, about 0.2 s through the development tunnel, and the phone path to the agent.

The conversation page shows the p90 and the p50 (nearest rank), the number of replies and of talk-overs, the response time on each agent turn that answers a caller reply, and a band on the recording for each wait: green under 1 s, amber from 1 to 2 s, red over 2 s. `GET /api/v1/runs/<run id>` pools the replies of the latest attempts into `response_p50_ms` and `response_p90_ms`. `GET /api/v1/conversations?run_id=<run id>&sort=-response_p90_ms` lists the slowest conversations first. Calls without the measurement show "Latency not measured". See `docs/decisions/0017-response-time-at-trumans-connection.md`.

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

## Runs

A run starts several scenarios of one agent together and repeats them. Each scenario runs with its own persona. In the console, select scenarios in the agent's list and click Run. Through the API:

```sh
curl -X POST localhost:8000/api/v1/runs -H "Authorization: Bearer $TRUMAN_API_TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: nightly-2026-10-01' \
  -d '{"agent_id": "<agent id>", "scenario_ids": ["<scenario id>", "<scenario id>"], "repeats": 3, "max_parallel": 2, "start_interval_s": 10}'
```

- The run starts one conversation for each repeat of each scenario, all of them or none. Every conversation pins the agent, scenario and persona versions that were current when the run was created.
- `max_parallel` sets how many conversations of the run can be on the line at once. `start_interval_s` sets the least time between two conversation starts; a conversation starts when a worker takes it. When Truman calls the agent, the call follows a few seconds later; when the agent calls Truman, the start sends the trigger, and the call can come up to the agent's dial window later. Without them, the run has no limit and no delay of its own. Both protect the agent under test. Single test calls start before the queued conversations of runs.
- `max_duration_s` is the time limit of each call, 10 to 1800 seconds, default `TRUMAN_DEFAULT_MAX_DURATION_S` (300).
- `max_turns` is how many agent turns the caller answers, 1 to 100, default `TRUMAN_DEFAULT_MAX_TURNS` (20). At the next turn the caller says goodbye and says nothing more, and the conversation ends with `turn_limit`. The caller ends the call on its own only when its goal is achieved, so this limit ends the calls that go nowhere. When the caller ends the call, Truman waits until both sides are quiet for 8 seconds before it hangs up, so the agent can close the call. See `docs/decisions/0013-close-before-hang-up.md`.
- `background_noise` plays one background in every conversation of the run, for example `{"sound": "none"}` to compare a run with and without noise. Left out, each conversation plays its persona's setting.
- `max_retries`, default 1, is the number of extra attempts for a conversation that ends with an error on Truman's side or on the line. 0 turns retries off. Conversations in the "did not connect" group are not tried again.
- `GET /api/v1/defaults` returns the values the server uses when a request leaves these fields out: `max_duration_s`, `max_turns`, and `max_retries` of a run. The console fills its forms with them.
- The same `Idempotency-Key` with the same body returns the first run, so a client can send a request again safely. The same key with another body is refused.
- `POST /api/v1/runs/<run id>/cancel` cancels the queued conversations and asks the workers to end the calls on the line. The run shows `cancelling` until those calls end.
- `GET /api/v1/runs/<run id>` counts the latest attempt of each conversation by outcome: waiting, in progress, completed, did not connect, error and cancelled. These are facts about the calls, not verdicts about the agent.

| Variable | Purpose |
| --- | --- |
| `TRUMAN_MAX_ACTIVE_CONVERSATIONS` | The most conversations one worker runs at once, default 4. |
| `TRUMAN_MAX_RUN_CONVERSATIONS` | The most conversations one run starts, the scenarios times the repeats, default 200. Retries are not counted. |
| `TRUMAN_MAX_RUN_REPEATS` | Default 10. |
| `TRUMAN_MAX_RUN_RETRIES` | Default 3. |
| `TRUMAN_MAX_RUN_START_INTERVAL_S` | The largest `start_interval_s` a run can ask for, default 600. |

The phone provider limits the calls of the whole account that can be on the line at once. Keep the sum of `TRUMAN_MAX_ACTIVE_CONVERSATIONS` over all workers, plus any other use of the same account, under that limit. Otherwise Plivo refuses the extra calls: it refuses the call request (HTTP 403, "Concurrency Limit Breached"), or it ends the call with hangup cause 5030. When Truman calls the agent, such a conversation ends with an error; when the agent calls Truman, it shows as a call that did not connect. The max parallel of a run does not protect the account, because two runs can each use it in full.

## CLI

`truman` is a command-line client for this API, for coding agents, CI and people. Each command prints the server's JSON on stdout, and progress, hints and errors on stderr. It exits 0 when the command worked, and 1 otherwise.

To set it up through your coding agent, paste this into the agent:

```text
Install the Truman CLI with curl -fsSL https://raw.githubusercontent.com/plivo-labs/truman/main/install.sh | bash, then run npx skills add plivo-labs/truman -g and follow the truman skill to test my voice agent.
```

Until the release builds exist, build it from source with Go:

```sh
cd cli && go build -o ~/.truman/bin/truman .
export PATH="$HOME/.truman/bin:$PATH"                    # add this line to your shell profile too
truman auth login --server http://localhost:8000         # or set TRUMAN_URL and TRUMAN_API_TOKEN
truman run start --agent <agent id> --all --wait
```

`truman guide` prints how a coding agent tests a voice agent with it; the same text is the skill in `cli/skill/SKILL.md`. To install the skill into your coding agent, run `npx skills add plivo-labs/truman`.

## Develop

```sh
docker compose -f docker/compose.dev.yaml up --build
```

Open http://localhost:5173. Python and frontend changes reload in place.

Without Docker: `uv sync && uv run prek install`, start Postgres (`docker compose -f docker/compose.dev.yaml up postgres`), export `TRUMAN_API_TOKEN` and `TRUMAN_DATABASE_URL=postgresql+asyncpg://truman:truman@localhost:5433/truman`, then `uv run truman-server api --reload`, `uv run truman-server worker` in a second terminal, and, in `frontend/`, `bun install && bun run dev`. Tests start their own Postgres through Docker.
