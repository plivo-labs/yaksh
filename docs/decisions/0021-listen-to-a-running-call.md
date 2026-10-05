# 0021 Listen to a running call

Date: 2026-10-05
Status: accepted

## Decision

The console plays a live call (`running` or `ending`) in stereo: the agent on the left, the caller on the right, with the caller's background noise.

- **Tap.** A Pipecat observer on the call's pipeline worker keeps two kinds of push: `InputAudioRawFrame` from the input transport (the agent) and `OutputAudioRawFrame` from the output transport (the caller). The output transport pushes a frame only after it sent it, with the noise mixed in. Each piece keeps the time of its push on the pipeline's clock.
- **Worker to API.** Each call has a sender with its own Postgres connection. It listens on the call's want channel and sends the audio with `NOTIFY` on the call's audio channel, only for 10 s after the last request. It sends one batch every 50 ms, with `synchronous_commit` off. An empty `NOTIFY` marks the end of the call.
- **API to console.** `GET /api/v1/conversations/{id}/listen` listens on the audio channel, asks on the want channel every 5 s, and streams each message with its length in front. It answers 404 for a call that is not live.
- **Display.** A Listen button in the conversation page's Audio card starts the audio. While it plays, the card draws it with the recording player's lanes, one peak for each 10 ms, from the first piece scheduled after Listen, over a span that doubles from 60 s as the call goes on.
- **Playback.** The console schedules each piece as an `AudioBufferSourceNode` in an 8 kHz `AudioContext`. It plays each piece 0.4 s after the fastest delivery, at its place on the call's timeline. A late piece is dropped, and after 0.5 s of late pieces the delay is measured again. A side that falls more than 0.3 s behind its place skips audio until it is within 0.05 s. A side more than 0.05 s behind drops only its quiet pieces.

## Why

- No part uses Plivo, so a websocket transport for agents needs no change. The pipeline runs at 8 kHz for every transport.
- The observer runs on its own queue, so a listener cannot slow the call. A processor after the output transport was on the call path, and the agent's audio waited behind the caller's speech: the listener was 3.4 s behind.
- The worker and the API already share Postgres. `NOTIFY` delivered in 1 to 13 ms and needs no new port, secret or worker address, so it also works with several workers.
- On real calls, the listener played 0.43 s behind the call (p95 0.45 s), the two sides were within 30 ms, and no audio came late. Earlier rules lost about 200 ms of the agent every 10 s, or put the sides up to 3.5 s apart.
- A streamed `fetch` sends the bearer token in a header, as the live transcript does. Scheduled buffers work on a plain HTTP address; an AudioWorklet needs HTTPS or localhost.

## Cost

- Each running call holds one more Postgres connection, also when nobody listens, because the sender must hear the requests. Each listener holds one more on the API. `LISTEN` needs a session-level connection, so a pooler in transaction mode cannot carry them.
- The audio is about half a second behind the call. Less delay loses more audio to jitter.
- The worker sometimes gets the agent's audio late at the start of a call, all at once. The console skips that audio: 2.3 to 2.5 s in the measured calls.
- The page schedules the audio on its main thread. A very busy page could make audio late.

## Other options

- An internal listen server on the worker: as fast as `NOTIFY`, but a new port, a secret, and a worker address for each worker. The worker's port 8770 was not an option: it runs only with Plivo, and the public tunnel publishes it.
- A live file on the shared volume: about 30 ms slower, disk writes for each call, and cleanup.
- Pipecat's `AudioBufferProcessor`: it pads the shorter side with silence, so its pieces drift, and they are too big for one `NOTIFY`.
- Pipecat's transports for the listener: each takes one client and cannot join a running pipeline.
- A WebSocket to the console: no faster, and the token must go in a subprotocol header, which proxies can log.
- An AudioWorklet: no better timing, and it needs HTTPS or localhost.
- Plivo's own features: they work only with Plivo, and Plivo allows one stream for each call.
