---
name: truman
description: Test a voice agent with Truman's CLI. Start test calls of its scenarios, wait for them, and read why calls failed. Use after a change to a voice agent's prompt, flow or code, or when the user asks to test a voice agent with Truman.
---

# Test a voice agent with Truman

Truman phones a voice agent with a simulated caller and records each call. The `truman` command talks to a Truman server. Every command prints the server's JSON on stdout. Progress, hints and errors go to stderr. A command exits 0 when it worked, and 1 otherwise.

## Before you test

1. Truman calls the deployed agent, at the number or start URL in its Truman record. A local code change does nothing until it is deployed there. If you are not sure that the change is deployed, ask the user.
2. Find the Truman agent for this repo in the repo's notes, for example its AGENTS.md. If it is not there, ask the user once, and offer to note it there. `truman agent list --external-id <name>` finds an agent by its external ID.
3. Run `truman auth status`. If it fails, ask the user to run `truman auth login`, or to set `TRUMAN_URL` and `TRUMAN_API_TOKEN`.

## Run tests

Calls cost money and minutes. Run the fewest scenarios that test the change. Ask the user before a large run. Never start runs in a loop.

1. `truman scenario list --agent <agent-id>` lists the scenarios. `truman scenario view <id>` shows the goal and criteria of one.
2. `truman run start --agent <agent-id> --scenario <id> --scenario <id>` starts a run and prints it. `--all` runs every scenario of the agent.
3. `truman run wait <run-id> --timeout <less than your tool's time limit>` waits for the run. If it says that the run did not end, call it again. Stopping `run wait` does not stop the run.
4. `run wait` exits 0 when every call completed. Otherwise it prints the next command to run.

For one call: `truman conversation start --agent <agent-id> --scenario <id> --wait` prints each event as one JSON line as it happens, then the conversation.

## Read failures

1. `truman conversation list --run <run-id> --latest-attempts --group error,did_not_connect` lists the calls that failed.
2. `truman conversation view <id>` shows one call: `status`, `end_reason`, `caller_reason`, `failure_reason`, `transcript`, `wire_events`, and the scenario with its criteria.
3. Likely causes, by `end_reason`:
   - `no_answer` or `no_call`: the agent is not deployed, or its number is wrong.
   - `trigger_failed`: the URL, headers or body of the outbound trigger.
   - `agent_silent`: the agent stopped talking.
   - `turn_limit`: the call went nowhere.
   - `duration_limit`: the agent is too slow, or it loops.
   - `error`: a problem on Truman's side or on the phone line, not in the agent.
4. "completed" means that the call ran to its end, not that the agent did its job. Read the transcript against the scenario's criteria.

## After a fix

Deploy the fix. Start a run with only the scenarios that failed, then run the full set once.

## Rules

- Never print the API token, and never write it to a file.
- `truman --help` and `truman <command> --help` list every flag.
