# 0021 Evaluate saved calls in a service of their own

Date: 2026-10-05
Status: accepted

## Decision

- The worker saves the call and its raw facts: the recording, the audio that each caller reply sent (`caller-voice.wav`), the reply windows and the agent's media coverage. In the transaction that saves the call, it queues one evaluation for that call. A conversation cancelled before its call connected gets no evaluation.
- A separate service, `truman-server evaluator`, claims queued evaluations, computes the metrics from the saved files and rows, and stores one row for each metric.
- A claim holds a lease that the evaluator renews while it works. Each claim increments a fencing number, and a write that does not carry the latest number changes nothing. When an evaluator stops, another evaluator claims its evaluation after the lease ends.
- A failed attempt waits 2^n seconds, at most 5 minutes, before the next claim. After 10 attempts, the evaluation ends failed. This includes attempts that stopped their evaluator, so a call that crashes the evaluator cannot stop it again and again.

## Why

- Silero holds Python's GIL while it loads its model (about 35 ms) and while it analyzes audio. In the worker, this work ran next to live calls. A thread does not help, because the GIL stops the other threads too.
- A call has 5 s to stop. Measurement after the call used part of that time, and a stopped call lost its outcome when the measurement took too long.
- When a metric changes, it can run again over the stored files without a new call.
- Postgres already holds the work queue for calls with `FOR UPDATE SKIP LOCKED`. The evaluations use the same pattern, so Truman needs no other queue.

## Cost

- One more service to run. Without it, calls finish but get no metrics.
- The metrics come a few seconds after the call ends.

## Other options

- A process pool in the worker. Rejected: the call still waited for it on its stop path, and each worker had one more process to manage.
- A task queue on Redis. Rejected: a new dependency for work that Postgres already does.
