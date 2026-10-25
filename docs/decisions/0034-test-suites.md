# 0034 A test suite starts the runs of several agents together and gives one result

Date: 2026-10-24
Status: accepted

## Context

- After a change to a voice platform, a team tests many agents: the same agent in several languages, or over phone and text. Each run starts by hand, and each result is read alone.
- CI needs one command that starts all of them and one exit code.
- A run's pass rate leaves out the calls that did not complete and the calls that a user stopped. A gate on it can pass a run where most calls never got a verdict.

## Decision

- A suite has a name, a required pass rate (a whole percent, 80 by default) and a list of entries. An entry is one agent over one connection (phone or text), its scenarios and its run settings. A suite can mix agents, and one agent can be in a suite more than once.
- An entry lists its scenarios, each with its personas, data sets and answers, or it uses all the agent's scenarios with one list of answers. "All" is read again at each start. The personas of listed scenarios are fixed when the suite is saved.
- A suite run starts one normal run for each entry, all of them or none, in one transaction. Each run uses the newest version of its agent. A deleted agent, scenario, persona or data set refuses the start, and one refusal names each entry and its problem. A save keeps such an entry and shows the problem, so broken entries can be fixed one at a time.
- Each suite run keeps a copy of the required pass rate. Yaksh computes the result of each run, and of the suite run, each time it is read:
  - A call that the judges score and whose evaluation is not finished keeps the run judging, also when the run was cancelled.
  - A call where no caller talked must pass by the agent rules (decision 0032), or the run fails.
  - With 95% or more of the other calls scored, the pass rate decides. Below that, the run passes if it reaches the rate even when every call that is not scored counts as failed, fails if it misses the rate even when every one counts as passed, and is otherwise not decided. Calls that did not complete, and calls that a user stopped, count as not scored.
  - The suite run is running or judging while one of its runs is, then failed if one run failed, cancelled if one was cancelled, not decided if one is not decided, and otherwise passed.
- `yaksh suite run --wait` exits with 0 only when the suite run passed. The console and the CLI read the result from the server.
- A save sends the revision that the client read, so two editors cannot drop each other's entries. A suite cannot be deleted while one of its suite runs has a run at work. Two suite runs of one suite can run at the same time.

## Why

- Normal runs keep every run page, metric and retry as they are. A suite adds a parent, not a new kind of run.
- All or none: a CI job that started half its runs gives a result that nobody can read.
- The server computes the result once, so the console, the API and the CLI cannot disagree.
- The gate counts the calls that the run page leaves out, because a test that never got a verdict must not pass.

## Cost

- Migration 0004: `suites`, `suite_entries`, `suite_entry_scenarios`, `suite_entry_scenario_personas`, `suite_runs`, and `runs.suite_run_id` with `runs.suite_position`.
- A start locks the suite, then the agents, scenarios and personas of all its entries in that order, before any snapshot. A save locks the suite and key-shares the rows that its entries point to in the same order.
- The suite's pass rate can be lower than the one the run page shows for the same run, when calls did not complete or a user stopped them.

## Other options

- A webhook trigger for a suite. Rejected for now: the CLI covers CI, and the API covers other callers.
- One required pass rate for each entry. Rejected: one number for a suite is easier to read and to set.
- Entries as one JSON column. Rejected: the database could not check the references to agents, scenarios and personas.
