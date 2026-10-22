# 0032 The worker's conversation limits are settings

Date: 2026-10-22
Status: accepted. Changes 0027 and 0030.

## Context

- `YAKSH_MAX_ACTIVE_CONVERSATIONS` (default 4) and `YAKSH_MAX_ACTIVE_TEXT_CONVERSATIONS` (default 20) set how many phone and text conversations one worker runs at once. A worker read them only when it started.
- To change the phone limit, an operator changed the deployment and started the worker again. A restart stops the live calls of the worker.
- The right phone limit is found by tests: raise it, look at the worker stalls and the response times of the calls, then raise it again or go back. Each step needed a new deployment.
- The worker reads the stored settings again at each poll, before it claims conversations.

## Decision

- The limits are settings: `worker.phone_conversations_at_once` (1 to 50, default 4) and `worker.text_conversations_at_once` (1 to 100, default 20), in the **Each worker** panel of the **Limits** tab.
- The worker reads them at each poll. A higher value applies at the next poll. A lower value stops no live conversation: the worker claims no new conversation of that transport until it has fewer than the new value.
- The two environment variables are removed.

## Why

- An operator changes the limit in a few seconds and sees the result in the next calls, with no deployment and no restart.
- The limit is not a timing that the API and the workers must agree on (0030). A worker with an old value for one poll is safe.

## Cost

- All workers use one value. A worker on a smaller host cannot have a lower limit than the others. To use hosts of different sizes, give them the same size, or set the limit for the smallest host.

## Other options

- An environment ceiling for each worker, plus a target on the Settings page that cannot be more than the ceiling. Rejected for now: it keeps a deployment step for every change above the ceiling.
- Keep the environment variables (0030). Rejected: each step of a capacity test needs a deployment and stops the live calls.
