# 0016 A call connects when its audio starts

Date: 2026-10-04
Status: accepted; it replaces the moment that 0015 chose

## Decision

The `connected` wire event marks the start of the call's audio: the moment Plivo's stream opened, or the agent's first frame when Plivo's timestamp puts that frame earlier. Talk time and the call recording count from this moment.

The worker knows this moment only when the call ends, because the agent's frames move onto Yaksh's clock by the shortest delay of all the frames. So the caller sends `connected` when the stream opens, and sends it again at the end when the moment is earlier. The second event replaces the first. The duration limit still counts from the moment the stream opened, because the worker must start that timer at once.

## Why

- 0015 assumed that Plivo sends the agent's audio from its `start` event. Real calls show that this is not true. In 4 calls on 2026-10-04 where the agent spoke first, Plivo stamped the agent's first frame 773 to 789 ms before Yaksh took the stream, and about 300 ms after Plivo reported the answer.
- Plivo sent those frames in one burst after the stream opened, and Yaksh transcribed them. But the recording started at `connected` and cut them: 780 to 800 ms, which was 35 to 65% of the greeting.
- With `connected` and the recording at the first frame, the same calls keep all of the greeting, the turns stay within 20 ms of their place in the recording, and the recording has less than 80 ms of silence before the first sound.
- The console plays a turn from its time minus the time of `connected`, so it needs no change.

## Cost

- Talk time is longer by the time from the agent's first frame to the stream opening: about 0.8 s in these calls.
- A viewer of the live event stream sees the first `connected` time. The stored conversation has the final time.
- The duration limit and talk time count from moments up to about 0.8 s apart.

## Other options

- Start the recording at `answered`, and make the console count from `answered`. Rejected: `answered` comes from Plivo's HTTP callbacks, which arrive late and out of order (one call logged `answered` before `ringing`), so a late callback cuts the greeting again. It also adds about 0.3 s of silence before the agent speaks.
- Keep `connected` at the stream opening and keep a separate start for the recording. Rejected for the reason in 0015: the console would need two zero points.
- Never move `connected` before `answered`. Rejected for the same callback timing.
