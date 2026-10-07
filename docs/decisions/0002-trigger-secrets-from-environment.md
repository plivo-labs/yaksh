# 0002 Trigger secrets come from environment variables

Date: 2026-09-29
Status: replaced by 0027 (trigger secrets on the Settings page)

## Decision

A trigger refers to a secret as `{{env.YAKSHA_TRIGGER_<NAME>}}`. Yaksha reads the value from its environment when it sends the request. Only names that start with `YAKSHA_TRIGGER_` are allowed.

## Why

- Secrets never reach the database, agent versions, API responses or logs. The stored request shows them masked.
- No encryption code or key management in Yaksha.
- The prefix stops a user with the API token from sending Yaksha's own secrets, such as `PLIVO_AUTH_TOKEN`, to a URL they control. Yaksha's own settings, including the trigger signing key, are outside the prefix.
- Cost: a new or changed secret needs a `.env` edit and a worker restart.

## Other options

- Secrets stored in the database and managed in the UI. Rejected for now: needs encryption, key rotation and leak checks. Parked in `docs/ideas/trigger-secrets-in-ui.md`.
- Any environment variable allowed. Rejected: exposes Yaksha's own secrets.
