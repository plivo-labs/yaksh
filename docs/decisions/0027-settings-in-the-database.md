# 0027 Settings in the database, the environment only to start

Date: 2026-10-07
Status: accepted, changed by 0029 (the receiving application is on the Settings page), 0030 (worker timings in code) and 0032 (the worker's conversation limits are settings). Replaces 0002. Changes 0004, 0007 and 0023.

## Decision

The provider keys, the models, the limits, the Plivo Auth ID and Auth token, the trigger signing key and the trigger secrets are on the Settings page of the console. Yaksh keeps them in one database row, `app_settings`, and reads them only from there.

- The row holds the values that differ from the defaults. The defaults stay in code, so a release can change a default.
- Each secret is encrypted with AES-256-GCM. The key comes from `YAKSH_ENCRYPTION_KEY` through HKDF-SHA256. Each write has a random 96-bit nonce. The name of the secret is the associated data, so a value cannot move to another secret. A stored value starts with a format byte.
- The row has a version that grows with every change. Each process compares the version at the start of each piece of work (a call, an evaluation, an API request) and reads the row again when it changed. A call keeps the settings it started with.
- The environment keeps what Yaksh needs before it can open the database, and what changes the deployment: the database URL, the API token, `YAKSH_ENCRYPTION_KEY`, the ports, `YAKSH_PUBLIC_URL`, file storage and the maximum number of conversations on one worker. 0030 moved the other worker and evaluator values out of the environment. The Plivo application and the test numbers moved out of the environment with 0029.
- Yaksh does not start without `YAKSH_ENCRYPTION_KEY`, or when the key cannot decrypt the stored secrets.
- Before Yaksh saves a key, it sends one small request to the provider, and saves the key only when the provider accepts it. The Plivo Auth ID and Auth token are saved and checked together.
- A key is bound to its address. A new `llm.base_url` or `deepgram.base_url` removes the key of that provider, unless the same change saves a new key, which is then checked at the new address. Otherwise a token holder could point the base URL at their own server and receive the saved key with the next request.
- A run cannot start while a key that a call needs is not saved.
- A stored value that a later release refuses falls back to its default when Yaksh reads it, with a warning, so the Settings page still opens. Writes stay strict.
- The API never returns a secret: only whether it is saved, and its last 4 characters.
- A trigger names a secret as `{{secrets.<NAME>}}`. The signing key is not one of these secrets, so a template cannot send it.
- The judges use the LLM provider of the caller. There is no separate judge key, and no setting turns the judges off.
- `yaksh settings export` writes the settings as YAML, with each saved secret as `${NAME}`. `yaksh settings apply` applies such a file with the values of the variables from the environment of the CLI. The console imports and exports the same format.

## Why

- A change of a key or a model needed an `.env` edit and a restart of the API, the worker and the evaluator. A wrong key showed only when a call failed.
- One source for each setting. Yaksh does not read the environment for a setting on the page, so no `.env` value can silently differ from the page.
- The database can hold the keys only if a copy of it without the encryption key shows no key.
- The export and the CLI keep a declarative path for scripts, CI and a database reset, without keys in the file.

## Cost

- A new install has no keys until someone adds them. The console opens on Settings until the LLM provider key is saved, and shows the missing keys.
- If `YAKSH_ENCRYPTION_KEY` is lost, the stored secrets are lost. The user enters them again. Key rotation is not built.
- One API token can read and change all settings. The API never returns a secret, and a provider key goes only to the address it was checked with, so a leaked token cannot read a provider key back through Yaksh. It can still use the keys by starting calls. A trigger secret goes wherever a trigger template sends it, so a token holder can send it to any public URL, as before this change.

## Other options

- Env values fill the database at the first start, and the page owns them after that. Rejected: a later `.env` change does nothing, and nothing tells the user why.
- An env value wins and shows as read-only on the page. Rejected: two sources for one setting.
- Fernet. Rejected for AES-256-GCM, which binds each value to its setting through the associated data.
- An outside secret store, such as Vault or a cloud KMS. Not now: Yaksh is self-hosted, and a hard dependency on one store is the wrong default.
