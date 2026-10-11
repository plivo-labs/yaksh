# Yaksha

Simulate, evaluate and improve AI agents. Open source, runs on your own infrastructure. Fully customizable, with the best defaults. By [Plivo](https://plivo.com).

## Run

```sh
cp docker/.env.example docker/.env   # set YAKSHA_API_TOKEN and YAKSHA_ENCRYPTION_KEY
docker compose -f docker/compose.yaml up --build
```

Open http://localhost:8000 and enter the API token. The API is under `/api/v1` and takes the token as a bearer header.

The API listens on port 8000 and the worker listens on port 8770. To use a different port, set `PORT` for that process. Hosting platforms such as Railway, Render, Fly and Cloud Run set `PORT` for each service.

This starts Yaksha on your computer. To install it on a server, follow the steps in `docs/content/docs/self-hosting.mdx`: a server needs a fixed public address for the worker and `up -d`.

## Settings

Yaksha keeps its configuration in two places:

- **Environment variables** hold what Yaksha needs before it can open its database: `YAKSHA_API_TOKEN`, `YAKSHA_DATABASE_URL`, `YAKSHA_ENCRYPTION_KEY`, `YAKSHA_PUBLIC_URL`, file storage, and a few worker values. The API and the worker read them when they start.
- **The Settings page** of the console holds the provider keys, the models and the limits. Yaksha keeps them in the database, each key encrypted with AES-256-GCM under `YAKSHA_ENCRYPTION_KEY`. A change applies to the next call, with no restart. A call in progress keeps the settings it started with.

`YAKSHA_ENCRYPTION_KEY` must have 32 characters or more (`openssl rand -base64 32`). Yaksha does not start without it, or when it cannot decrypt the saved keys. Keep a copy: without it, the saved keys are lost and you must enter them again.

On a new install, the console opens on Settings until the LLM provider key is saved. Each key is checked with its provider before Yaksha saves it, and the API never returns a saved key. `yaksha settings export` writes the settings as YAML, with each key as a `${NAME}` placeholder, and `yaksha settings apply -f FILE` applies such a file with the keys from the environment. See `docs/content/docs/configuration.mdx` and `docs/decisions/0027-settings-in-the-database.md`.

## Caller

The worker phones agents with a [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline: Deepgram hears the agent, a model at the LLM provider plays the persona, and ElevenLabs speaks. The LLM provider is any API with OpenAI's Responses endpoint, such as OpenAI or an Azure OpenAI resource at `https://<resource>.openai.azure.com/openai/v1/`. The caller, scenario writing and the judges use it. The caller model defaults to `gpt-6-luna`; a reasoning model that accepts it gets reasoning effort `none`, so the caller answers fast. Do not use gpt-4.1: over this API it can write several replies in one response, and the caller speaks them all. See `docs/decisions/0023-the-caller-model-is-gpt-6-luna.md`.

## Phone

Agents are called on the real phone network through [Plivo](https://www.plivo.com): the worker dials the agent's number from one of your Plivo numbers, receives the call audio over a Plivo stream and hangs up through the API. The Plivo Auth ID and Auth token are on the Phone tab of Settings. Plivo has to reach the worker, so it needs a public HTTPS address; until both are in place, conversations cannot be started.

| Variable | Purpose |
| --- | --- |
| `YAKSHA_PLIVO_NUMBERS` | Optional. By default the worker calls from every voice-capable number on the account; set a comma-separated E.164 list to use only those. Each running phone conversation takes one number, so the pool bounds phone concurrency. |
| `YAKSHA_PUBLIC_URL` | The public `https://` address that reaches the worker's port 8770. Phone calls are off without it. |

The worker reads the account's numbers when it starts and again when the Plivo keys in Settings change.

For development, `scripts/tunnel.sh` opens a Cloudflare quick tunnel to the worker (no account needed) and prints the `YAKSHA_PUBLIC_URL` line to put in `docker/.env`; the hostname changes every time the tunnel starts. For a fixed hostname, run a [named tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) that routes your hostname to the worker (`http://localhost:8770` from the host, `http://worker:8770` from a container on the Compose network), or put the worker behind any other public HTTPS host that also passes WebSocket connections. Either way, the API and the worker read `YAKSHA_PUBLIC_URL` at startup, so recreate both after changing the value. In `docker/compose.yaml` the API service is `yaksha`:

```sh
docker compose -f docker/compose.yaml create --force-recreate yaksha worker
docker compose -f docker/compose.yaml start yaksha worker
```

In `docker/compose.dev.yaml` the services are `api worker`.

Pick a persona, create the agent with its number and a scenario that runs with the persona, then start a run of the scenario. `GET /api/v1/personas` lists the built-in personas. A conversation uses the scenario's persona. The wire events show `ringing`, `answered` and `connected` as the call progresses:

```sh
curl localhost:8000/api/v1/personas -H "Authorization: Bearer $YAKSHA_API_TOKEN"
curl -X POST localhost:8000/api/v1/agents -H "Authorization: Bearer $YAKSHA_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Support line", "agent_number": "+14155550100", "brief": "Answers billing questions and resets passwords."}'
curl -X POST localhost:8000/api/v1/agents/<agent id>/scenarios -H "Authorization: Bearer $YAKSHA_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Book a table", "persona_id": "<persona id>", "instructions": "You want a table for two tonight. Once the agent confirms the booking, say goodbye.", "criteria": ["Reads the time and party size back before it books."], "data_sets": [{"name": "Priya", "known_facts": [{"name": "Name", "value": "Priya Raman"}]}]}'
curl -X POST localhost:8000/api/v1/runs -H "Authorization: Bearer $YAKSHA_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"agent_id": "<agent id>", "scenarios": [{"scenario_id": "<scenario id>"}]}'
```

## Surroundings

A persona's `surroundings` are what the agent hears behind the caller: noise `sounds` (street, cafe, office, car, TV, crowd, kitchen, wind, each at its own level), or `auto` noise that comes and goes, and a `speaker`, a person who talks behind the caller (talks to the caller, on their own phone call, or a TV). Levels are in dB relative to the caller's voice: 0 dB is as loud as the caller. The surroundings play for the whole call and the recording includes them. Yaksha's own speech to text hears only the agent, so they change only what the agent hears.

When a run creates a conversation, Yaksha plans its sounds from the surroundings, the scenario version and the repeat, so the same scenario and repeat play the same sounds in every run. A retry plays the same plan. The call page shows when each sound played and what the speaker said. The sound files are in `src/yaksha/simulation/sounds/`. See `docs/decisions/0027-surroundings.md`.

## Response time

After each call is saved, the evaluator measures how long the agent made the caller wait. For each caller reply, the response time runs from the end of the caller's speech to the start of the agent's first speech after it. When the agent was still speaking at the end of the caller's speech, the time starts where the agent stopped. Before the caller has spoken, the time runs from the moment Yaksha's stream opened, so a slow greeting shows too. An agent that was already speaking then gets no value for the call's start, and neither does a call that Yaksha's caller opens. When the agent starts before the caller finishes, the reply is a talk-over and has no response time. A reply that the agent does not answer before the caller speaks again has no response time either, so the percentiles leave that wait out. The caller's goodbye and a wait over a gap in the agent's media get no value.

- The end of the caller's speech is where the voice detector last finds speech in the reply's own TTS audio, before Yaksha mixes in the surroundings. The TTS puts 0.03 to 0.35 s of quiet audio after the last word; this end leaves it out. A reply cut off before its TTS finished ends when Yaksha sent its last audio, the `caller_audio_end` wire event.
- The agent's speech comes from the voice detector of the live call, Pipecat's Silero VAD, with the same settings, run over the agent channel of the recording. A spoken "hmm" counts as speech. In tests, an agent's quiet "thinking" sound did not.
- Yaksha measures at its own connection, so the number includes the path between Yaksha and the agent's system, both ways. For a phone call, that is the path to Plivo, about 0.2 s through the development tunnel, and the phone path to the agent.

The conversation page shows the p90 and the p50 (nearest rank), the number of replies and of talk-overs, the response time on each agent turn that answers a caller reply, and a band on the recording for each wait: green under 1 s, amber from 1 to 2 s, red over 2 s. `GET /api/v1/runs/<run id>` pools the replies of the latest attempts into `response_p50_ms` and `response_p90_ms`. `GET /api/v1/conversations?run_id=<run id>&sort=-response_p90_ms` lists the slowest conversations first. Calls without the measurement show "Not measured". See `docs/decisions/0019-response-time-at-yakshas-connection.md`.

## Call metrics

After each call, the evaluator also computes metrics from what the call saved. `GET /api/v1/conversations/<conversation id>/evaluation` returns them with the verdicts and the state of the evaluation: `queued`, `running`, `done` or `failed`. A call that did not connect gets only `usage`. A call without a recording gets no speech metrics: a missing value, not a zero.

| Metric | What it holds | Flags |
| --- | --- | --- |
| `turn_taking` | One row for each caller reply and for the start of the call: when the agent answered, and how long the caller waited in silence. The caller's goodbye, a reply that the end of the call cut off, and the start of a call that Yaksha's caller opens expect no answer. A wait over a gap in the agent's media counts only up to the gap. A reply is unanswered when the caller spoke again before the agent answered. Counts: unanswered replies, talk-overs, waits of 3, 5 and 10 s or more, the longest wait. | `unanswered`, `long_wait` (5 s), `dead_air` (10 s), `media_gap` |
| `response_time` | The response times of the section above, over the waits that expected an answer, without the waits that a media gap cut short. | |
| `speech` | Where each side spoke. | |
| `speaking` | Each side's speech time before the caller's goodbye, the agent's share, and the agent's longest speech with no caller speech in it. | `monologue` (45 s) |
| `agent_repetition` | The same agent answer, given 3 or more times in a row, each time after a caller reply. | `repetition` |
| `capture_faults` | Faults on Yaksha's side: a caller error, caller turns that Plivo did not confirm as played before the last reply, a missing recording, no media or gaps in the media from the agent's side, a worker stall over 100 ms. A call whose worker stopped before it saved the call in full gets only `incomplete_record`. Read the other metrics of such a call with care. | one for each fault |
| `usage` | The caller's models and what they used, Plivo's billed duration, and the time from the call's start to ringing, answer and stream open. | |

`GET /api/v1/runs/<run id>/metrics` pools the metrics of the run's counted conversations: the latest attempt of each repeat, unless it was cancelled. It gives these numbers for the whole run, for each scenario category and for each persona surroundings:

- How many conversations are evaluated, pending or failed.
- The connection rate: calls whose audio started, of the calls that connected or did not connect. A call that failed after its audio started counts as connected. Yaksha's own errors before a call connected are counted on their own.
- The response time p50 and p90 over all the replies.
- The share of calls with a reply that the agent did not answer, with a talk-over, with a wait of 5 s or more, and with a wait of 10 s or more. A share counts calls, not replies, because the replies of one call are not independent of each other.
- How many calls raised each flag.

Each share comes with a 95% Wilson interval, so a run with few calls shows how little it can tell.

The same endpoint gives the run's verdict numbers in `verdicts`, over its judged calls: the counted calls that completed, that no one stopped, and whose evaluation gave a verdict or failed. A failed evaluation counts as unscored. Calls still in evaluation (`pending`) and calls evaluated with no judge model (`not_judged`) are left out and counted. The pass rate is the mean over scenarios of each scenario's passes over its scored calls, so a scenario with more calls does not count more. Coverage is the scored calls over the judged calls; below 0.95, read the worst-to-best range (unscored calls counted as fails, then as passes) as the main number. With five or more scenarios, a "this suite" 95% interval comes from random draws of each scenario's results, seeded by the run, so the same run always gives the same interval. `pass_hat_2` is the chance that two repeats of a scenario both pass. The numbers also list each criterion's outcomes, each agent rule's outcomes, the scenarios that both passed and failed, how many criteria and agent rules code, Jev and the judge model decided and how many no judge could decide, each persona's caller check results, and the judge versions the run used, with how many items each judged. The category grouping uses each scenario's category as it is now. The run's `response_p50_ms` and `response_p90_ms` use the same counted conversations.

## Judging

The evaluator also judges each completed call that no one stopped: one model call for each criterion of the scenario and for each LLM rule of the agent. Each judge reads the same evidence view of the call: the agent's brief, the caller's instructions and facts, the date, the call facts and the transcript. A judge quotes the transcript, and code checks each quote in its turn; an answer that fails the checks is asked again once. The verdicts are `pass`, `fail`, `not_applicable` and `unsure` (`hidden_action`, `not_confirmed_played`, `unclear`). A scenario passes when every criterion that applies passes; an `unsure` item that needs a hidden action counts as not applicable.

The judges use the LLM provider. A call evaluated while no LLM provider key is saved gets its code metrics and phrase rules only. The judge model (default `gpt-6-luna`), its reasoning effort (default `medium`), the most text one judge request holds (default 400,000 characters) and the timeout of the judges that read the agent's sources (default 180 s, one try) are on the Models tab of Settings. The TypeSafe key, on the Providers tab, is optional: it makes judging cheaper, because Jev, TypeSafe's classifier, answers each criterion and LLM rule first. Call transcripts are then sent to TypeSafe. Jev is most accurate in English.

Two more judges read the agent's own sources and only report, so they do not change a verdict. Instruction adherence runs when the agent has its `config`: it asks whether the agent kept the goal of its instructions, did the steps they require and stayed inside what they allow, and a fail quotes both the call and the instruction line. Hallucination runs when the agent has knowledge-base documents: it fails only an agent statement that a document contradicts, and quotes both; a fact the documents do not mention is not a failure, since the agent can know it from its own tools. Sources larger than the input limit make that item an error, `sources_too_large`.

The caller check looks at Yaksha's own caller, so that a test the caller broke never counts against the agent. Code finds facts first: the caller hung up while the agent had no closing words, the last turn is the caller's, the caller hung up within 10 s of "let me check", or the test's turn or time limit ended the call; the closing and wait phrases are English, so other calls get only the turn and limit facts. Then one model call, given the scenario's instructions and facts and the persona but not the caller's general prompt rules, finds where the caller broke its test and which criteria that changed. Only a wrong fact, an invented value, a scripted line the caller never said although it had a turn, or a hang-up its instructions did not allow is a finding; an early answer, two lines in one turn, other words with the same meaning or a goodbye is not. A criterion the caller likely changed is `blocked`: not scored, never the agent's failure. A possible effect keeps the verdict and marks it. On a call that a test limit ended, an unmet criterion the limit cut off is blocked too, and so is every unmet criterion when the caller check itself failed. A pass is never blocked. The caller check's own item never counts in the agent's results.

With a TypeSafe key, Jev answers every criterion and LLM rule of a call first, in one request, each as one choice: meets, fails, not applicable or cannot tell. Jev publishes only a pass, when it chooses meets with a probability of at least the Jev pass bar in Settings (default 0.95); such a pass has no reason and costs no model call. Every other answer, and any failure of Jev, goes to the judge model, which does not see Jev's answer. Each item keeps Jev's choice and probabilities.

An agent's rules check every judged call of that agent. An LLM rule says when it applies, when it passes and when it fails; its gate, `always` or `agent_spoke`, is checked in code first. A phrase rule is a required or forbidden phrase or regular expression in the agent's lines, checked in code: it matches the line as written or with numbers, dates and times in one written form, and a pattern has 0.5 s for each line. A rule with the role `deciding` counts in the conversation verdict. `GET /api/v1/agents/<agent id>/rule-results` gives each current rule's outcomes over the judged calls that ran it as it is written now, with its latest failed calls. A change to what a rule checks starts its results again, and so does a new name for an LLM rule, since the judge model reads it; a change of role does not. When the judge model fails for a while, its item waits and asks again; after the evaluator's last attempt, the item ends as an error and the call keeps its code metrics. `GET /api/v1/conversations/<conversation id>/evaluation` returns the verdicts, each item with its judge's answer, and the metrics.

## Labels and review

People check the judges by labeling items. A labeler answers an item pass, fail, not applicable, can't tell or blocked. A fail, can't tell or blocked also gives what went wrong, from a fixed list of reasons, and so does any label that differs from a machine answer the labeler can see; otherwise a reason is optional. The reason `other` needs a note. A label never changes the machine result. It sets the item's effective outcome: when the latest labels of all labelers agree, their answer; while they disagree, `pending`. The call's effective verdicts follow.

Each labeler has a named token. `POST /api/v1/labelers` with the admin token creates one and shows the token once; `DELETE /api/v1/labelers/{id}` revokes it and keeps its labels, and `POST /api/v1/labelers/{id}/token` gives the same labeler a new one. A labeler token opens only the review routes under `/api/v1/review`: the queue, a judged call with its items and recording, and a label.

A share of the judged calls, the audit sample in Settings (default 0.1), is chosen for audit by a hash of the conversation id. The queue offers, for each week of calls, the first of them by that hash, up to the weekly audit budget in Settings (default 30). In an offered call, the items the judge model or Jev decided without an error are in the audit lane: each hides its machine result from a labeler until that labeler labels it, and the call's verdicts and the items code decided stay hidden until all of them are labeled. The server enforces this; a person who also holds the admin token can see the machine results elsewhere. Instruction adherence and hallucination stay out of the audit lane for now, since the review screen does not show the agent's config and documents. Every other label is ad hoc, including a label on a sampled call that the queue does not offer, and every label given with `seen` set, as from the "Label" link on a call's results in the console: it changes verdicts but never measures a judge, since a person chose the call or saw the machine's answer first.

`GET /api/v1/judges/agreement` counts each item once, by its first blind audit label. For each judge version it gives how often that label agrees with the version's answer, leaving out items the caller check blocked or the judge failed; for calls with a blind label on every criterion, how often the labels' scenario verdict agrees with the machine's; how often two labelers agree on an item; and how many offered calls are labeled in full. Each comes with a 95% Wilson interval. A judge version with no blind labels is not listed: it is not yet measured on your agents.

## Listen to a live call

On the page of a live call, **Listen** in the **Audio** card plays the call in stereo: the agent on the left, the caller on the right, with the caller's surroundings. The audio is about half a second behind the call. While it plays, the card draws it in the same lanes as the recording, from the first audio after Listen. **Stop listening** removes the drawing. After the call, the recording takes its place. It stops when the call ends, on a second click, or when you leave the page. Several people can listen to one call.

- The worker takes the audio inside its Pipecat pipeline with an observer, so it does not depend on Plivo, and a slow listener cannot slow the call.
- The worker sends a call's audio to the API with Postgres `NOTIFY`, only while someone listens: the API asks for it every 5 seconds while a listener stays.
- `GET /api/v1/conversations/<id>/listen` streams the audio while the call is `running` or `ending`, and answers 404 for any other call. The route's description in the API reference gives the format of its messages.
- Each running call holds one more Postgres connection, and so does each listener on the API. `LISTEN` needs a session-level connection, so a pooler in transaction mode cannot carry these connections.

See `docs/decisions/0021-listen-to-a-running-call.md`.

## Files

Uploaded files (PDF, TXT and MD documents about an agent) and the audio of each call are kept in S3-compatible storage. Yaksha does not start without it. The compose files run [SeaweedFS](https://github.com/seaweedfs/seaweedfs) for this, with its data in the `storage` volume. To use S3, R2 or another S3-compatible service instead, set:

| Variable | Purpose |
| --- | --- |
| `YAKSHA_S3_ENDPOINT` | The storage URL. Required. |
| `YAKSHA_S3_BUCKET` | The bucket, default `yaksha`. It must exist. |
| `YAKSHA_S3_ACCESS_KEY`, `YAKSHA_S3_SECRET_KEY` | The credentials. Required. |
| `YAKSHA_S3_REGION` | Default `us-east-1`. |

## Outbound agents

An outbound agent calls Yaksha. Yaksha sends the agent's trigger, a POST or GET request that makes the agent call one of Yaksha's numbers, and answers that call.

1. In the Plivo console, create an Application with answer URL `<YAKSHA_PUBLIC_URL>/incoming` and hangup URL `<YAKSHA_PUBLIC_URL>/incoming/hangup`, both `POST`, and link the numbers that receive test calls to it.
2. Set the variables below, then recreate the API and the worker as in Phone: the API reads `YAKSHA_PLIVO_APP_ID` and the worker reads all of them at startup, and a restart keeps the old values. The worker reads the Application and its numbers at startup and when the Plivo keys in Settings change, so restart it after a change in the Plivo console. The Numbers page says why outbound tests are off, if they are.
3. Create an agent with direction outbound, its trigger URL, headers and JSON body. In the trigger, `{{yaksha.number}}` is the number to call, `{{yaksha.conversation_id}}` the conversation, `{{agent_data.<name>}}` a value from the data set the call plays and `{{secrets.<NAME>}}` a trigger secret from the Phone tab of Settings.

| Variable | Purpose |
| --- | --- |
| `YAKSHA_PLIVO_APP_ID` | The Application from step 1. Outbound tests are off without it. |
| `YAKSHA_ALLOW_PRIVATE_TRIGGERS` | Optional. Allows `http` and private addresses as trigger URLs, for agents on your own network. Default off. |

The Phone tab of Settings also holds the signing key, which signs each trigger with `X-Yaksha-Signature` (HMAC-SHA256 over `<X-Yaksha-Delivery>.<X-Yaksha-Timestamp>.<body>`; see `docs/decisions/0004-signed-triggers.md`), and the number rest: how long a number rests after a test before it receives another outbound call, default 300 s.

## Runs

A run starts several scenarios of one agent together and repeats them. Each scenario runs with its own persona. In the console, select scenarios in the agent's list and click Run. Through the API:

```sh
curl -X POST localhost:8000/api/v1/runs -H "Authorization: Bearer $YAKSHA_API_TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: nightly-2026-10-01' \
  -d '{"agent_id": "<agent id>", "scenarios": [{"scenario_id": "<scenario id>"}, {"scenario_id": "<scenario id>", "persona_ids": ["<persona id>", "<persona id>"]}], "repeats": 3, "max_parallel": 2, "start_interval_s": 10}'
```

- The run starts one conversation for each repeat of each scenario and persona pair, all of them or none. A scenario with no `persona_ids` uses its own persona. Every conversation pins the agent, scenario and persona versions that were current when the run was created.
- `max_parallel` sets how many conversations of the run can be in progress at once, from the moment a worker takes one until it ends, so ringing and the wait for an outbound agent's call count too. `start_interval_s` sets the least time between two conversation starts; a conversation starts when a worker takes it. When Yaksha calls the agent, the call follows a few seconds later; when the agent calls Yaksha, the start sends the trigger, and the call can come up to the agent's dial window later. Without them, the run has no limit and no delay of its own. Both protect the agent under test.
- `max_duration_s` is the time limit of each call, 10 to 1800 seconds, default the call length in Settings (300).
- `max_turns` is how many agent turns the caller answers, 1 to 100, default the turns per call in Settings (20). At the next turn the caller says goodbye and says nothing more, and the conversation ends with `turn_limit`. The caller ends the call on its own only when its instructions are done, so this limit ends the calls that go nowhere. When the caller ends the call, Yaksha waits until both sides are quiet for 8 seconds before it hangs up, so the agent can close the call. See `docs/decisions/0013-close-before-hang-up.md`. A reply that ends the call without a word does not end it: the caller gets one more reply to speak in, and after that Yaksha says the goodbye for it. See `docs/decisions/0020-the-caller-speaks-before-it-ends-the-call.md`.
- `max_retries`, default 1 (0 when the retries limit in Settings is 0), is the number of extra attempts for a conversation that ends with an error on Yaksha's side or on the line. 0 turns retries off. Conversations in the "did not connect" group are not tried again.
- `GET /api/v1/defaults` returns the values the server uses when a request leaves these fields out: `max_duration_s`, `max_turns`, and `max_retries` of a run. The console fills its forms with them.
- The same `Idempotency-Key` with the same body returns the first run, so a client can send a request again safely. The same key with another body is refused.
- `POST /api/v1/runs/<run id>/cancel` cancels the queued conversations and asks the workers to end the calls on the line. The run shows `cancelling` until those calls end.
- `GET /api/v1/runs/<run id>` counts the latest attempt of each conversation by outcome: waiting, in progress, completed, did not connect, error and cancelled. These are facts about the calls, not verdicts about the agent.

The Limits tab of Settings caps a run: the most conversations one run starts, the scenarios times the repeats (default 200; retries are not counted), the most repeats (default 10), the most retries (default 3) and the largest `start_interval_s` (default 600). `YAKSHA_MAX_ACTIVE_CONVERSATIONS`, in the environment, is the most conversations one worker runs at once, default 4.

The phone provider limits the calls of the whole account that can be on the line at once. Keep the sum of `YAKSHA_MAX_ACTIVE_CONVERSATIONS` over all workers, plus any other use of the same account, under that limit. Otherwise Plivo refuses the extra calls: it refuses the call request (HTTP 403, "Concurrency Limit Breached"), or it ends the call with hangup cause 5030. When Yaksha calls the agent, such a conversation ends with an error; when the agent calls Yaksha, it shows as a call that did not connect. The max parallel of a run does not protect the account, because two runs can each use it in full.

## CLI

`yaksha` is a command-line client for this API, for coding agents, CI and people. Each command prints the server's JSON on stdout, and progress, hints and errors on stderr. It exits 0 when the command worked, and 1 otherwise.

To set it up through your coding agent, paste this into the agent:

```text
Install the Yaksha CLI with curl -fsSL https://raw.githubusercontent.com/plivo-labs/yaksha/main/install.sh | bash, then run npx skills add plivo-labs/yaksha -g and follow the yaksha skill to test my voice agent.
```

Until the release builds exist, build it from source with Go:

```sh
cd cli && go build -o ~/.yaksha/bin/yaksha .
export PATH="$HOME/.yaksha/bin:$PATH"                    # add this line to your shell profile too
yaksha auth login --server http://localhost:8000         # or set YAKSHA_URL and YAKSHA_API_TOKEN
yaksha run start --agent <agent id> --all --wait
```

`yaksha settings get` prints the settings, `yaksha settings export` writes them as YAML with each key as `${NAME}`, and `yaksha settings apply -f FILE` applies such a file, reading each `${NAME}` from the environment. Use them to set up an install from a script or CI, or again after a database reset.

`yaksha guide` prints how a coding agent tests a voice agent with it; the same text is the skill in `cli/skill/yaksha/SKILL.md`. To install the skill into your coding agent, run `npx skills add plivo-labs/yaksha`.

## Develop

```sh
docker compose -f docker/compose.dev.yaml up --build
```

Open http://localhost:5173. API and frontend changes reload in place. The worker does not reload: after a Python change, restart it with `docker compose -f docker/compose.dev.yaml restart worker`.

Without Docker: `uv sync && uv run prek install`, start Postgres and the file storage (`docker compose -f docker/compose.dev.yaml up -d postgres storage`), export `YAKSHA_API_TOKEN`, `YAKSHA_DATABASE_URL=postgresql://yaksha:yaksha@localhost:5433/yaksha`, `YAKSHA_S3_ENDPOINT=http://localhost:8333`, `YAKSHA_S3_ACCESS_KEY=yaksha` and `YAKSHA_S3_SECRET_KEY=yaksha-storage`, then `uv run yaksha-server api --reload`, `uv run yaksha-server worker` and `uv run yaksha-server evaluator` in two more terminals with the same exports, and, in another terminal in `frontend/`, `bun install && bun run dev`. Tests start their own Postgres through Docker.

The docs site is in `docs/` and uses [Fumadocs](https://fumadocs.dev): in `docs/`, `bun install && bun run dev`, then open http://localhost:3000/docs. Its API reference comes from `cli/openapi.json`.
