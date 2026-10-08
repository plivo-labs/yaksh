---
name: yaksha
description: Test a voice agent with Yaksha's CLI and improve it in a loop. Run its scenarios, wait for the judges' verdicts, read why calls failed, fix the agent, and run the failed scenarios again. Use after a change to a voice agent's prompt, flow or code, or when the user asks to test or improve a voice agent with Yaksha.
---

# Test and improve a voice agent with Yaksha

Yaksha phones a voice agent with a simulated caller and records each call. Then its judges check the call against the scenario's criteria and the agent's rules. The `yaksha` command talks to a Yaksha server. Every command prints the server's JSON on stdout. Progress, hints and errors go to stderr. A command exits 0 when it worked, and 1 otherwise. On 1, a line that starts with `failed:` means that the test ran and did not pass, and `error:` means that the command went wrong. `failed:` does not by itself mean that the agent is at fault: read why before you change the agent. A `next:` line, when there is one, gives the next command to run.

## Before you test

1. Yaksha calls the deployed agent, at the number or start URL in its Yaksha record. A local code change does nothing until it is deployed there. If you are not sure that the change is deployed, ask the user.
2. Find the Yaksha agent for this repo in the repo's notes, for example its AGENTS.md. If it is not there, ask the user once, and offer to note it there. `yaksha agent list --external-id <name>` finds an agent by its external ID.
3. Run `yaksha auth status`. If it fails, ask the user to run `yaksha auth login`, or to set `YAKSHA_URL` and `YAKSHA_API_TOKEN`.
4. `yaksha agent view <agent-id>` shows the agent. Its `config` is the copy of the agent's prompt or flow that the judges read. Compare it with the prompt or flow in the repo that you change. If they differ, update it (step 6 of the loop) before you test. If you cannot see the agent's prompt or flow, say so in your report and treat the copy as current.

## The loop

Calls cost money and minutes. Run the fewest scenarios that test the change, and ask the user before a large run.

1. **Run.** `yaksha scenario list --agent <agent-id>` lists the scenarios, and `yaksha scenario view <id>` shows the goal and criteria of one. `yaksha run start --agent <agent-id> --scenario <id> --scenario <id> --wait --timeout <less than your tool's time limit>` starts a run and waits. `--all` runs every scenario of the agent. The command waits for the calls, then for the judges ("judging: N calls pending"). It exits 0 only when every call completed and the judges passed every call. A call that they did not score, or whose evaluation failed, also gives exit 1.
   - When it says the run did not end, or the judges were not done, `yaksha run wait <run-id> --timeout <limit>` waits again. Stopping `run wait` does not stop the run. A Ctrl-C during `run start --wait` cancels the run.
   - When "judging" does not go down, `yaksha conversation list --run <run-id> --latest-attempts` shows the `evaluation` state of each call. Run `yaksha conversation evaluation <id>` on a `queued` call. With a `failure`, the judge model fails, and Yaksha tries again for 14 minutes or more. With no `failure`, the evaluator service (`yaksha-server evaluator`) is not running. Tell the user.
2. **See what failed.** `yaksha run metrics <run-id>`, in `verdicts`:
   - `pass_rate`: the mean over scenarios of passes over scored calls. `coverage`: scored calls over judged calls; below 0.95, read the `worst` to `best` range.
   - `scenarios`: each scenario with its calls, their conversation IDs and verdicts. A verdict is `pass`, `fail`, `not_scored` (the judges could not decide), or null (the evaluation failed).
   - `criteria`: each scenario criterion with its outcome counts. `inconsistent`: scenarios whose repeats disagree. `errors`: the number of criteria and agent rules that no judge could decide.
3. **See why a call failed.** `yaksha conversation evaluation <conversation-id>`:
   - `effective_scenario_verdict` decides the call: it comes from the scenario's criteria, after people's labels. `effective_conversation_verdict` also counts the agent's deciding rules.
   - `items`: one for each criterion (`criterion-N`), agent rule (`rule-<key>`) and report. Read `subject`, `effective_outcome` (`pass`, `fail`, `not_applicable`, `unsure`, `blocked`, `error`, `pending`), `decided_by` and `answer`.
   - `decided_by` says who decided: `llm` (the judge model), `code` (a fixed check in Yaksha) or `jev` (a fast classifier). With `llm`, `answer` holds the judge model's quotes and reasoning. With `code`, `answer` shows what the check found, or is empty when the check failed. `jev` only passes items, when it is very sure (`jev_probabilities`), and gives no `answer`: to check such a pass, read the transcript. `machine_outcome` is what the judges decided, and `effective_outcome` includes people's labels.
   - `unsure` with `effective_unsure_kind: unclear`: the call does not show the answer. Often the agent was vague or did not confirm. Read the transcript, and make the agent clear if that is the cause. With kind `not_confirmed_played`, the only evidence is in caller turns that were not played, or not confirmed as played. Find those turns in the transcript: if the agent spoke over the caller there, that is the agent's fault. Otherwise, run the scenario again.
   - Three items report on the call. They are not criteria:
     - `instructions` ("Follows its instructions") compares the call with the agent's `config`. It is present only when the agent has a config.
     - `hallucination` ("States no fact its documents contradict") is present only when the agent has knowledge-base documents.
     - `caller_check` ("Yaksha's caller kept to its test") checks Yaksha's caller. Its `answer.blame_risk` says how likely the caller changed the result. It can also block a criterion that the caller likely broke, or that the turn or time limit cut off. The blocked criterion shows why in `caller_effect`, and the call becomes not scored, not failed. Do not change the agent for it: run the scenario again.
   - An item with outcome `error` and an `error_reason` is a judge failure, not an agent failure. So is a failed evaluation: its `failure` says why. Run the scenario again, and tell the user when it fails again.
   - `metrics` describe the call. `metrics.usage.value.settings` are the models of Yaksha's caller, not of the agent.
4. **Read the call.** `yaksha conversation view <conversation-id>` shows the `transcript`, `wire_events`, `end_reason`, `caller_reason` and the scenario with its criteria. Find the turns that the judge quoted in the transcript, and the agent's lines around them. Each caller turn has a `provenance`: `transmitted` (the phone line played it), `cut` (the agent started to speak, and the rest was not played) or `unconfirmed` (no report that it played). `surroundings` is what the agent heard behind the caller: noise `sounds` or `auto` noise, and a `speaker`, a person who talks behind the caller; `sounds` lists when each one played and what the speaker said. When `validity.ok` is false, Yaksha's caller had a fault (`validity.reasons`): do not trust the call, and run it again. A `worker_stall` flag in the run's metrics means that Yaksha's worker paused, which delays the audio of its calls. `metrics.capture_faults.value.worker_stall` in the evaluation gives the time (`at_ms`) and the length (`max_ms`). When the call went wrong near that time, run it again before you change the agent.
5. **Fix** the agent's code, prompt or flow, for the cause that the evidence shows. Deploy the fix, or ask the user to.
6. **Update Yaksha's copy.** When the prompt or flow changed: `yaksha agent update <agent-id> --config-file <prompt-or-flow-file>`. The instruction adherence judge checks the call against this text.
7. **Run again.** Run only the scenarios that failed (step 1 with their IDs). When they pass, run the full set once. Stop when the full set passes. When the same scenario still fails after two fixes, stop and tell the user what you found and what you tried.

## Response times

The agent's response time is the wait from the end of the caller's speech to the start of the agent's answer. Under 1 s is good, 1 to 2 s is slow, and over 2 s is too slow.

- `yaksha conversation view <id>`: `latency` has `p50_ms`, `p90_ms`, `replies` and `talked_over`. Each agent turn has `response_ms`, and `talked_over` when the agent started before the caller finished.
- `yaksha run view <run-id>`: `response_p50_ms` and `response_p90_ms` over the run's calls.
- `yaksha conversation list --run <run-id> --latest-attempts --sort -response_p90_ms` lists the slowest calls first.
- `long_wait` in the run's metrics counts calls with one wait of 5 s or more. A call under that limit can still be too slow by the limits above.

## Calls that did not complete

`yaksha conversation list --run <run-id> --latest-attempts --group error,did_not_connect` lists them. Likely causes, by `end_reason`:

- `no_answer` or `no_call`: the agent is not deployed, or its number is wrong.
- `trigger_failed`: the URL, headers or body of the outbound trigger.
- `agent_silent`: the agent stopped talking.
- `turn_limit`: the call went nowhere.
- `duration_limit`: the agent is too slow, or it loops.
- `error`: a problem on Yaksha's side or on the phone line, not in the agent.

The judges check only completed calls that no one stopped.

## Rules

- Never print the API token, and never write it to a file.
- Never start runs in an endless loop: the loop above stops.
- `yaksha --help` and `yaksha <command> --help` list every flag.
