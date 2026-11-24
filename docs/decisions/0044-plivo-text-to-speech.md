# 0044 Plivo's text to speech speaks with the Plivo account, through Pipecat's Plivo service

Date: 2026-11-25
Status: accepted. Changes 0037 (a fifth text-to-speech provider with its own Auth ID and Auth token, and a client of its own that retried and ended calls on its own rules).

## Context

- Plivo's text to speech, Koyal, is on Plivo's public API: the Realtime API at `/v1/Account/{auth_id}/TTS/Realtime` and the voice list at `/v1/Account/{auth_id}/TTS/Voices`. A Plivo account's Auth ID and Auth token open it, as they open the calls. Its one model is `koyal-v1`.
- The routes that Yaksh's own client used answer 404, so that client could not speak.
- The API takes English only with its region (`en-IN`, `en-US`, `en-GB`, `en-AU`). Yaksh's English is `en`.
- Pipecat has a Plivo service (pipecat-ai/pipecat#6987) that does what Yaksh's client did, on this API.

## Decision

- **Provider.** The provider is Plivo, as the other providers carry their company's name. Its model is Koyal v1 (`koyal-v1`), sent with each reply and recorded with each call.
- **Account.** Koyal speaks with the Auth ID and Auth token of the Plivo account that makes the calls: one login, as one Sarvam key both hears and speaks. Its address, `https://api.plivo.com` by default, is a setting that takes only `https`, and the Auth ID and Auth token are bound to it, as every key is bound to its address. The account's own check reaches `https://api.plivo.com`; at another address, Koyal also speaks one word there.
- **Service.** A Plivo voice speaks through Pipecat's `PlivoTTSService`, as the other providers speak through Pipecat's own services. Until a Pipecat release has it, Yaksh takes Pipecat from the pull request's commit.
- **Errors.** A Plivo error acts as the other providers' errors do: the service reports it, the caller records a caller error, and the call goes on while the service is usable.
- **Language.** An Indian language is sent by name. English, and a caller that can switch languages, send no language, so the API uses `auto`: it reads English in the voice's own region and finds the language of each sentence.

## Why

- The Plivo account in Settings already opens Koyal; a second Auth ID and Auth token for the same API is one more pair to keep in step.
- One behaviour for every provider's errors makes a run's caller errors mean the same thing for every voice.
- The voice's region is the right one for its numbers and dates; Yaksh's English has no region to send.

## Consequences

- Migration 0011 renames the provider in the database, in the voices, the personas and the stored copies of a voice; gives these voices Koyal's model; and deletes the provider's own address, Auth ID and Auth token. The Plivo account's Auth ID and Auth token were never checked at that address, and the old default, `https://in.tts.plivo.com`, answers 404 to these routes. Koyal uses `https://api.plivo.com` until another address is saved with the Auth ID and Auth token.
- A new address removes the Plivo Auth ID and Auth token, so the calls stop too until they are saved again with it.
- A process of the previous release cannot read a row of the renamed provider. Change no voice, persona or setting until every process runs this version.
