# Trigger secrets in the UI

## Problem

Trigger secrets come from `YAKSHA_TRIGGER_*` environment variables. A new or changed secret needs a `.env` edit and a worker restart.

## Idea

A Secrets page to add, replace and delete secrets, used as `{{secret.<name>}}` in triggers.

## Cost

- Secrets encrypted in the database, with the key in an environment variable.
- Key rotation re-encrypts every secret.
- API responses, logs and errors must never contain a secret.
