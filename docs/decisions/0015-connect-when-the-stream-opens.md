# 0015 A call connects when Plivo's stream opens

Date: 2026-10-04
Status: accepted

## Decision

The `connected` wire event marks the moment Truman takes the stream, right after Plivo's `start` event. Talk time, the duration limit and the call recording count from this moment. Before, it marked the start of Truman's pipeline, when Pipecat calls `on_client_connected`.

Pipecat's `on_client_connected` now only starts the caller's opening: the first words when the caller speaks first, or nothing when the agent speaks first. A call is connected for all of `PhoneCaller._talk`, so `CallState` no longer keeps a connected time.

## Why

- Plivo sends the agent's audio from its `start` event, but Truman's pipeline starts later. In one logged call, the pipeline was built about 0.3 s after the `start` event.
- An agent that speaks first can talk in that time. In all 18 stored calls where the agent spoke first, its first audio came within 16 ms of the old `connected`: the agent was already speaking while its frames waited in the socket. A recording that starts at the old moment cuts the start of the greeting.
- The recording must start at `connected`, because the console plays a turn from its time minus the time of `connected`.
- The code already describes talk time as "from the moment the call connected" and the duration limit as counted "from the moment the stream connected". The new moment matches these words.

## Cost

- Talk time is longer by the time the pipeline takes to start.
- A failure after the stream opens and before the pipeline starts now ends with the call connected: the status is `invalid`, not `failed`. Both are in the error group, so a run still tries the conversation again.
- A stop in that time ends a connected call: its status is `completed`, not `cancelled`. Its outcome group is still cancelled.

## Other options

- A separate event for the start of the recording. Rejected: the console would need two zero points, one for the recording and one for the turns.
- Keep the old moment and cut the agent's audio from before it. Rejected: the recording loses the start of the greeting.
- Keep the old moment and put the earlier audio at the start of the recording. Rejected: every later sound on the agent's side moves late by the same time, which is the recording bug that this change fixes.
