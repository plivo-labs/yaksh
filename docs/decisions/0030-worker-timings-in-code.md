# 0030 Worker timings are fixed in code

Date: 2026-10-14
Status: accepted. Changes 0027.

## Context

- Eight environment variables set the evaluator concurrency, the judge call concurrency, the poll intervals, the heartbeat, the leases and the end timeout: `YAKSH_EVALUATOR_CONCURRENCY`, `YAKSH_EVALUATOR_JUDGE_CONCURRENCY`, `YAKSH_WORKER_POLL_INTERVAL_S`, `YAKSH_WORKER_HEARTBEAT_S`, `YAKSH_WORKER_LEASE_S`, `YAKSH_EVALUATOR_POLL_INTERVAL_S`, `YAKSH_EVALUATOR_LEASE_S` and `YAKSH_END_TIMEOUT_S`.
- No user changed the timings. Each one was a value that a user could set wrong.
- The API and every worker must use the same worker lease. The API reads it in `seen_within` to find the live workers. A worker with a different value reaps the conversations of a live worker, or keeps the conversations of a stopped one.
- A value on the Settings page applies when each process reads the settings again. Thus a change of a lease on the page applies at different times in different processes.

## Decision

- The evaluator concurrencies are settings: `evaluation.evaluations_at_once` (1 to 32, default 2) and `evaluation.judge_calls_at_once` (1 to 64, default 8), in the **Evaluation** panel of the **Models** tab. They follow the rate limits of the LLM provider, which the user knows and can change. The evaluator reads them each time it looks for work, so a change applies without a restart.
- The timings are fixed in `src/yaksh/timings.py`: worker poll 0.5 s, worker heartbeat 1 s, worker lease 30 s, evaluator poll 2 s, evaluator lease 60 s, end timeout 5 s. A `Timings` value holds them. Tests give a different `Timings` value with shorter times.
- `YAKSH_MAX_ACTIVE_CONVERSATIONS` stays in the environment. It follows the CPU and the memory of the worker host, which can be different for each worker.

## Why

- One value for the lease in all processes. No configuration can make the API and a worker disagree.
- The concurrencies are on the page with the LLM provider and its models, where a user looks after a rate limit error.

## Cost

- To change a timing, a user changes the code and builds Yaksh again.

## Other options

- All values on the Settings page. Rejected: a lease change applies at different times in different processes, and the heartbeat must stay much shorter than the lease.
- An environment ceiling for the maximum active conversations, plus a target on the Settings page that cannot be more than the ceiling. Not decided yet.
