---
name: truman
description: Test a voice agent with Truman's CLI and improve it in a loop. Run its scenarios, wait for the judges' verdicts, read why calls failed, fix the agent, and run the failed scenarios again. Use after a change to a voice agent's prompt, flow or code, or when the user asks to test or improve a voice agent with Truman.
---

# Test and improve a voice agent with Truman

Truman phones a voice agent with a simulated caller and records each call. Then its judges check the call against the scenario's criteria and the agent's rules. The `truman` command talks to a Truman server. Every command prints the server's JSON on stdout. Progress, hints and errors go to stderr. A command exits 0 when it worked, and 1 otherwise. On 1, the last stderr line often gives the next command to run.

## Before you test

1. Truman calls the deployed agent, at the number or start URL in its Truman record. A local code change does nothing until it is deployed there. If you are not sure that the change is deployed, ask the user.
2. Find the Truman agent for this repo in the repo's notes, for example its AGENTS.md. If it is not there, ask the user once, and offer to note it there. `truman agent list --external-id <name>` finds an agent by its external ID.
3. Run `truman auth status`. If it fails, ask the user to run `truman auth login`, or to set `TRUMAN_URL` and `TRUMAN_API_TOKEN`.
4. `truman agent view <agent-id>` shows the agent. Its `config` is the copy of the agent's prompt or flow that the judges read. If it is older than the agent's current prompt or flow, update it (step 6 of the loop) before you test.

## The loop

Calls cost money and minutes. Run the fewest scenarios that test the change, and ask the user before a large run.

1. **Run.** `truman scenario list --agent <agent-id>` lists the scenarios, and `truman scenario view <id>` shows the goal and criteria of one. `truman run start --agent <agent-id> --scenario <id> --scenario <id> --wait --timeout <less than your tool's time limit>` starts a run and waits. `--all` runs every scenario of the agent. The command waits for the calls, then for the judges ("judging: N calls pending"). It exits 0 only when every call completed and the judges passed every call. A call that they did not score, or whose evaluation failed, also gives exit 1.
   - When it says the run did not end, or the judges were not done, `truman run wait <run-id> --timeout <limit>` waits again. Stopping `run wait` does not stop the run. A Ctrl-C during `run start --wait` cancels the run.
   - When "judging" does not go down, `truman conversation list --run <run-id> --latest-attempts` shows the `evaluation` state of each call. Run `truman conversation evaluation <id>` on a `queued` call. With a `failure`, the judge model fails, and Truman tries again for 14 minutes or more. With no `failure`, the evaluator service (`truman-server evaluator`) is not running. Tell the user.
2. **See what failed.** `truman run metrics <run-id>`, in `verdicts`:
   - `pass_rate`: the mean over scenarios of passes over scored calls. `coverage`: scored calls over judged calls; below 0.95, read the `worst` to `best` range.
   - `scenarios`: each scenario with its calls, their conversation IDs and verdicts. A verdict is `pass`, `fail`, `not_scored` (the judges could not decide), or null (the evaluation failed).
   - `criteria`: each scenario criterion with its outcome counts. `inconsistent`: scenarios whose repeats disagree. `errors`: the number of criteria and agent rules that no judge could decide.
3. **See why a call failed.** `truman conversation evaluation <conversation-id>`:
   - `effective_scenario_verdict` decides the call: it comes from the scenario's criteria, after people's labels. `effective_conversation_verdict` also counts the agent's deciding rules.
   - `items`: one for each criterion, rule and report. Read `subject`, `effective_outcome` (`pass`, `fail`, `not_applicable`, `unsure`, `blocked`, `error`, `pending`) and `answer`, which holds the judge's quotes and reasoning.
   - The instruction adherence, hallucination and caller check items only report. But the caller check can block a criterion that Truman's caller likely broke, or that the turn or time limit cut off. A `blocked` criterion makes the call not scored, not failed. Do not change the agent for it: run the scenario again.
   - An item with outcome `error` and an `error_reason` is a judge failure, not an agent failure. So is a failed evaluation: its `failure` says why. Run the scenario again, and tell the user when it fails again.
4. **Read the call.** `truman conversation view <conversation-id>` shows the `transcript`, `wire_events`, `end_reason`, `caller_reason` and the scenario with its criteria. Find the turns that the judge quoted in the transcript, and the agent's lines around them.
5. **Fix** the agent's code, prompt or flow, for the cause that the evidence shows. Deploy the fix, or ask the user to.
6. **Update Truman's copy.** When the prompt or flow changed: `truman agent update <agent-id> --config-file <prompt-or-flow-file>`. The instruction adherence judge checks the call against this text.
7. **Run again.** Run only the scenarios that failed (step 1 with their IDs). When they pass, run the full set once. Stop when the full set passes. When the same scenario still fails after two fixes, stop and tell the user what you found and what you tried.

For one call: `truman conversation start --agent <agent-id> --scenario <id> --wait --timeout <limit>` prints each event as one JSON line as it happens, then the conversation, then the evaluation of a completed call. It exits 0 only when the call completed, no one stopped it, and the judges passed it, or gave no verdict because they are off.

## Response times

The agent's response time is the wait from the end of the caller's speech to the start of the agent's answer. Under 1 s is good, 1 to 2 s is slow, and over 2 s is too slow.

- `truman conversation view <id>`: `latency` has `p50_ms`, `p90_ms`, `replies` and `talked_over`. Each agent turn has `response_ms`, and `talked_over` when the agent started before the caller finished.
- `truman run view <run-id>`: `response_p50_ms` and `response_p90_ms` over the run's calls.
- `truman conversation list --run <run-id> --latest-attempts --sort -response_p90_ms` lists the slowest calls first.

## Calls that did not complete

`truman conversation list --run <run-id> --latest-attempts --group error,did_not_connect` lists them. Likely causes, by `end_reason`:

- `no_answer` or `no_call`: the agent is not deployed, or its number is wrong.
- `trigger_failed`: the URL, headers or body of the outbound trigger.
- `agent_silent`: the agent stopped talking.
- `turn_limit`: the call went nowhere.
- `duration_limit`: the agent is too slow, or it loops.
- `error`: a problem on Truman's side or on the phone line, not in the agent.

The judges check only completed calls that no one stopped.

## Rules

- Never print the API token, and never write it to a file.
- Never start runs in an endless loop: the loop above stops.
- `truman --help` and `truman <command> --help` list every flag.
