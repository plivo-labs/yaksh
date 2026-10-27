# 0036 Caller reply time, step by step

Date: 2026-10-28
Status: accepted

## Decision

For each reply of the phone caller, Yaksh records where the time went, from the end of the agent's speech to the caller's first audio, with Pipecat's own latency breakdown (`UserBotLatencyObserver` with `enable_metrics=True`).

- `caller/reply_times.py` subclasses the observer. A reply counts only when the caller's model started a response in its stretch and no fixed line (`TTSSpeakFrame`) or machine line (a `TTSStartedFrame` with the machine mark) did. Pipecat runs the breakdown's handler in a task of its own, so the observer sets a `ContextVar` with the closing audio start around Pipecat's handling of each `BotStartedSpeakingFrame`; the handler's task copies that context and reads its own start.
- Each part is cut to the stretch, and `pipeline` is what the named parts leave, so the parts add up to the reply's time. When Pipecat drops a transcript that came before the voice detector's stop (pipecat-ai/pipecat#5921), the wait from that stop to the model's request is named `turn_detection`.
- The worker writes one log line per reply, `caller_reply_time {json}`, with flat fields and every known part as `<part>_ms`, 0 when absent.
- The conversation keeps the replies in `caller_reply_times` (`audio_index`, `total_ms`, `steps`); the evaluator turns them into the `caller_reply_time` metric (nearest-rank percentiles, parts zero-filled).
- A caller turn carries the `audio_index` of the audio start that played it, through its playout, so the API puts each reply's time on its own turn.
- `GET /api/v1/settings/caller-reply-times` groups the replies of the last 7 days by caller model and effort, by when the calls ran, without invalid calls.

## Why

- The caller's reply time decides how a test call feels to the agent, and the caller's model is a choice in Settings. A total alone does not say if the time goes to the turn check, the model or the voice.
- Pipecat's breakdown names each part from the frames themselves, so Yaksh does not keep a timer of its own beside it.
- Operators of a long-lived install read latency over days from their log store, not from one call. One flat line per reply works with any store that can parse JSON in a line.

## Cost

- `enable_metrics=True` adds one metrics frame for each service response and a check of the TTS audio level until speech starts.
- The parts follow Pipecat's definitions. A Pipecat update can move time between parts; the log line carries Yaksh's version for that.
- Pipecat stamps a moment when its observer's queue takes the frame, so a busy event loop adds a little to the later parts.
- Only replies of the caller's model count: a nudge after a long silence is not a slow reply.

## Other options

- A timer of Yaksh's own from the VAD stop to the first audio. Rejected: it gives the total, not the parts.
- Matching breakdowns to replies by time. Rejected: the handler can run after later frames, and Pipecat can derive a moment after the audio start, so a time match picks the wrong reply. The context and the playout identity are exact.
- Leaving #5921's time as `pipeline`. Rejected: on real calls it held up to 5 s of smart-turn waiting in most replies.
