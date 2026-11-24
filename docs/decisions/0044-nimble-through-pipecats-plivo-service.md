# 0044 Nimble speaks through Pipecat's Plivo service

Date: 2026-11-24
Status: accepted. Changes 0037 (Nimble had a client of its own, which retried and ended calls on its own rules).

## Context

- Plivo moved Nimble to the routes of its public API: the Realtime API at `/v1/Account/{auth_id}/TTS/Realtime` and the voice list at `/v1/Account/{auth_id}/TTS/Voices`. The old routes answer 404, so Yaksh's own Nimble client could not speak.
- The API takes English only with its region (`en-IN`, `en-US`, `en-GB`, `en-AU`). Yaksh's English is `en`.
- Pipecat has a Plivo service (pipecat-ai/pipecat#6987) that does what Yaksh's client did, on the new API.

## Decision

- **Service.** A Nimble voice speaks through Pipecat's `PlivoTTSService`, as the other providers speak through Pipecat's own services. Until a Pipecat release has it, Yaksh takes Pipecat from the pull request's commit.
- **Errors.** A Nimble error acts as the other providers' errors do: the service reports it, the caller records a caller error, and the call goes on while the service is usable. The retry of a reply with no audio and the end of the call on any error, from 0037, are gone.
- **Language.** An Indian language is sent by name. English, and a caller that can switch languages, send no language: the API reads English in the voice's own region and finds the language of each sentence.
- **Address.** The default address is `https://api.plivo.com`; `https://us.api.plivo.com` is the US.

## Why

- One behaviour for every provider's errors makes a run's caller errors mean the same thing for every voice.
- The voice's region is the right one for its numbers and dates; Yaksh's English has no region to send.
