# 0025 Every conversation belongs to a run

Date: 2026-10-06
Status: accepted

## Decision

Yaksh has no single test calls. To place one call, start a run of one scenario with 1 repeat. `run_id` and `repeat` are required on every conversation. The API has no `POST /api/v1/conversations`, the console has no Start call, Ring or Trigger button, and the CLI has no `conversation start`.

## Why

- A single call and a run of one scenario did the same thing. Two ways to start a call confused users.
- A run has the same options (time limit, turns, background noise) and adds repeats, retries, verdicts and metrics.
- In local use, 265 of 271 calls were in runs.
- The worker, the reaper and the result write each had a separate path for calls without a run. With one path, that code is gone.

## Cost

- A conversation cannot use a persona other than its scenario's. To test a scenario with another caller, change its persona (0011).
- The CLI cannot stream a call's events. `run start --wait` shows the result when the run and the judges are done. The console still shows a call live.
- An existing database must delete its conversations without a run, and the rows that refer to them, before the schema change.
