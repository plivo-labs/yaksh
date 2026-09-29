# Load-balanced workers

## Problem

Truman supports one worker per public URL. The worker that starts a call waits in memory for the audio stream (`PendingStream`, `src/truman/caller/plivo_server.py`). With several workers behind one URL, the stream can reach another worker, which refuses it.

## Production

The flow runner stores the call config in Redis and returns a stream URL for the agent-runner load balancer. Any pod that gets the stream loads the config and runs the call.

## Options

1. **One worker.** Keep one worker per URL and raise `max_active_conversations`.
2. **Store the owner's URL.** Each worker has its own public URL, stored on the conversation at claim. Any worker that gets a Plivo webhook points the stream at the owner's URL.
3. **Any worker runs the call** (as in production), with Postgres or Redis:
   - Any worker can answer Plivo webhooks.
   - The worker that gets the stream takes over the conversation lease and builds the call from the stored conversation.
   - Hangup reports are stored with the conversation.
4. **Sticky sessions.** Not possible: Plivo requests carry no marker a load balancer can route on.

## Cost of option 3

- Refactor of the worker, the caller, and the lease code.
- A stream can reach a worker with no free call slot.
