# 0044 Plivo's text to speech speaks with the Plivo account, through Pipecat's Plivo service

Date: 2026-11-25
Status: accepted. Changes 0037 (a fifth text-to-speech provider with its own Auth ID and Auth token, and a client of its own that retried and ended calls on its own rules).

## Context

- Plivo's text to speech is on Plivo's public API: the Realtime API at `/v1/Account/{auth_id}/TTS/Realtime` and the voice list at `/v1/Account/{auth_id}/TTS/Voices`. A Plivo account's Auth ID and Auth token open it, as they open the calls. Its one model is Koyal v1 (`koyal-v1`).
- The routes that Yaksh's own client used answer 404, so that client could not speak.
- The API takes English only with its region (`en-IN`, `en-US`, `en-GB`, `en-AU`). Yaksh's English is `en`.
- Pipecat has a Plivo service (pipecat-ai/pipecat#6987) that does what Yaksh's client did, on this API. No Pipecat release has it yet.

## Decision

- **Provider.** The provider is Plivo, as the other providers carry their company's name. Its model is Koyal v1 (`koyal-v1`), sent with each reply and recorded with each call.
- **Account.** A Plivo voice speaks with the Auth ID and Auth token of the Plivo account that makes the calls: one login, as one Sarvam key both hears and speaks. It speaks at Plivo's API, `https://api.plivo.com`, where the account's own check reaches the account, so that check covers the voices. The address is not a setting.
- **Service.** A Plivo voice speaks through Pipecat's `PlivoTTSService`, as the other providers speak through Pipecat's own services. Until a Pipecat release has it, Yaksh takes Pipecat from the pull request's commit.
- **Errors.** A Plivo error acts as the other providers' errors do: the service reports it, the caller records a caller error, and the call goes on while the service is usable.
- **Language.** An Indian language is sent by name. English, and a caller that can switch languages, send no language, so the API uses `auto`: it reads English in the voice's own region and finds the language of each sentence.

## Why

- The Plivo account in Settings already opens Plivo's text to speech; a second Auth ID and Auth token for the same API is one more pair to keep in step.
- Plivo's public docs give one address for the API. Yaksh is for outside users, not for Plivo's own infrastructure (AGENTS.md), and an address setting would serve only the latter.
- One behavior for every provider's errors makes a run's caller errors mean the same thing for every voice.
- The voice's region is the right one for its numbers and dates; Yaksh's English has no region to send.

## Consequences

- Migration 0011 renames the provider in the database, in the voices, the personas and the stored copies of a voice; gives these voices the model `koyal-v1`; and deletes the provider's own address, Auth ID and Auth token. The old default address, `https://in.tts.plivo.com`, answers 404 to these routes.
- The upgrade stops every process of the previous release (api, worker and evaluator) before the first process of this version starts: a stop-then-start deploy, not a rolling one. This release is an exception to the rule that the previous version keeps working during a rolling deploy (AGENTS.md): a process of the previous release cannot read a row of the renamed provider, and a call that it ends writes `nimble` back into the call's stored voice (`conversations.caller_settings`), which this version cannot read. A deploy that stops each old process just before its new one starts, one service after another, is not enough: the previous worker still runs while the new api applies 0011.
- Until a Pipecat release has the service, the image build fetches Pipecat from GitHub.

## Other options

- Copy Pipecat's Plivo service into Yaksh. Rejected: every other provider speaks through Pipecat's own service, and a copy is a second service to keep in step with the pull request. The pin is one line in `pyproject.toml`, which a Pipecat release replaces.
- Wait for a Pipecat release with the service. Rejected: until then, Plivo voices cannot speak, because the old routes answer 404.
- A separate Auth ID and Auth token for speech. Rejected: they open the same API as the account that makes the calls.
- An address setting, as the other providers have. Rejected: Plivo's public docs give one address, and a setting would serve only Plivo's own infrastructure.
- A release that reads both `nimble` and `plivo` before the rename, so that a rolling deploy works. Rejected: it is one more release for a provider whose voices could not speak in the previous release, and the reader of the old value would stay for a provider that no longer exists.
