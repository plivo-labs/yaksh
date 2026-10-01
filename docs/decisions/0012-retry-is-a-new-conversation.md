# 0012 A retry is a new conversation

Date: 2026-10-01
Status: accepted

## Decision

When a conversation of a run ends with an error on Truman's side or on the line, and the run allows another attempt and is not cancelled, Truman queues a new conversation. It has attempt + 1, `retry_of` pointing to the one it replaces, and a copy of its inputs: the pinned versions, the caller prompt, the nudge, the time limit, the run and the repeat. The result write and the reaper make the retry under the run's lock, in the transaction that ends the attempt. Only the latest attempt of each repeat of each scenario counts.

## Why

- The failed attempt keeps its transcript, recording, failure reason and timing for diagnosis.
- Each attempt has the shape of any conversation, so the worker, the API and the console read it with no new code.
- The copied caller prompt keeps the run's versions and "today", so a retry tests the same thing.

## Cost

- Every reader of run results must skip the attempts that a retry replaced: a conversation that another one's `retry_of` points to. Evaluation must use the same rule.

## Other options

- Reset the failed conversation and run it again. Rejected: it loses the failed transcript and reason.
- A table of attempts under one conversation. Rejected: a second shape for the worker, the API and the console.
