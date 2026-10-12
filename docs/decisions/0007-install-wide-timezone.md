# 0007 One install-wide timezone, "today" fixed at creation

Date: 2026-09-29
Status: accepted, changed by 0027 (the time zone is on the Settings page)

## Decision

`YAKSH_TIMEZONE` (default UTC) sets the caller's "today". Yaksh computes it when the conversation, or the run that creates it, is created and writes it into the caller prompt. A retry copies the prompt, so it keeps the "today" of the attempt it replaces.

## Why

- Scenario facts use relative dates such as "next Thursday", so the caller needs a today.
- The caller prompt is frozen at creation, so what the caller was told is exactly what is stored.
- Cost: a conversation that waits in the queue past midnight uses the previous day.

## Other options

- A timezone for each agent or scenario. Rejected for now: more settings for a rare need.
- Compute today when the call starts. Rejected: the stored prompt would differ from what the caller got.
