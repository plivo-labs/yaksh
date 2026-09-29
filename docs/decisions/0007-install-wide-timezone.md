# 0007 One install-wide timezone, "today" fixed at creation

Date: 2026-09-29
Status: accepted

## Decision

`TRUMAN_TIMEZONE` (default UTC) sets the caller's "today". Truman computes it when the conversation is created and writes it into the caller prompt.

## Why

- Scenario facts use relative dates such as "next Thursday", so the caller needs a today.
- The caller prompt is frozen at creation, so what the caller was told is exactly what is stored.
- Cost: a conversation that waits in the queue past midnight uses the previous day.

## Other options

- A timezone for each agent or scenario. Rejected for now: more settings for a rare need.
- Compute today when the call starts. Rejected: the stored prompt would differ from what the caller got.
