# Listen to a live call

## Problem

People can follow a running call only as text. The conversation page streams the transcript while the call runs, and the recording plays after the call ends. Nobody can hear a call as it happens.

## Today

- The worker has both audio streams: the caller audio it sends and the agent audio from Plivo. It records both.
- The worker and the API share only Postgres. The worker writes turns and wire events on each heartbeat; the API polls them (`stream_events`, `src/truman/simulation/conversations.py`) and sends them to the browser as server-sent events.
- That path suits text, not audio. Audio is 50 frames a second in each direction, and a listener needs it within about a second.

## Idea

1. The worker sends the call audio on a listen socket per conversation, on its HTTP server (port 8770).
2. The API accepts the browser's socket with the bearer token, connects to `ws://worker:8770/listen/{conversation_id}` on the Docker network with an internal secret, and relays the frames.
3. The conversation page gets a Listen button that plays the audio with Web Audio. Listen only.

Rules:

- Port 8770 is behind the public tunnel for Plivo. The listen route refuses requests without the internal secret, so call audio never reaches the internet.
- A slow or stuck listener loses frames. It never slows the call.
- The socket closes when the call ends.

## Several workers

The lease row says which worker holds a call, but not how to reach it. Each worker must report an internal address. See [Load-balanced workers](load-balanced-workers.md).

## Size

About a day with one worker.

## Open question

One mixed stream, or stereo with the caller on the left and the agent on the right?
