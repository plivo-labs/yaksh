# 0041 Agent traces

Date: 2026-10-30
Status: accepted. Builds on 0019 (the wait is measured at Yaksh's connection) and 0036 (the caller's reply time and its parts).

## Decision

An agent can send its OpenTelemetry (OTel) traces to Yaksh. Yaksh then divides each wait of a phone call into the agent's parts and the rest of the wait.

- **Endpoint.** `POST /api/v1/otlp/v1/traces` takes OTLP over HTTP with protobuf, with or without gzip. Other formats get 415.
- **Trace token.** One token for each install, made in Settings › Traces. It is `yks_` and 40 random characters, and Yaksh keeps only its hash. It opens only the OTLP endpoint, and the endpoint takes no other token. Yaksh checks the token before it reads the body. A new token replaces the old one, which stops at once. With no token, the endpoint refuses all requests.
- **Limits.** 8 MB for the body, 32 MB after gzip, and 20,000 spans in one request; more gets 413. A span with a bad ID, a bad time or a kept value of the wrong type is rejected alone, in `partial_success`.
- **What Yaksh keeps.** The spans that a reader uses (LiveKit Agents: `agent_session`, `user_turn`, `eou_wait`, `eou_detection`, `agent_turn`, `llm_node`, `tts_node`, `function_tool`, `agent_speaking`; Pipecat: `conversation`, `turn`, `llm`, `tts`), with their timing values only. A span with a link key and another name is kept as its key only. All other spans and all content attributes are dropped.
- **Link keys.** `yaksh.conversation_id`, or `yaksh.number` as E.164. A span whose number is not one of Yaksh's numbers is dropped, unless it also has a conversation ID that is a UUID: it comes from a call that is not a test.
- **Wait.** While a trace token exists, the evaluation of a connected phone call waits until 30 s after the call. This lets the last exports arrive. Pipecat sends the span with the key when the call ends. A call that also waits for its agent record waits until both are ready.
- **Linking**, when the call is evaluated:
  - A trace that the call owns from an earlier evaluation stays its trace.
  - Each trace with the call's ID belongs to the call, except a trace with two calls' IDs.
  - Else the candidates have the call's number, no owner, no conversation ID, and a span from 5 s before the connection to 5 s after the end. A candidate passes when its clock lag is from -2 s to +7 s, and it aligns with the recording at an offset from -2 s to +2 s. Each candidate that passes links, unless two of them overlap in time.
  - A call can have more than one trace: an agent can serve a call in sessions one after another, each with its own trace. Yaksh reads each trace alone, as the rules of a reader hold in one session, and aligns their speech starts together. A call claims all its traces in one transaction, so that a failure leaves none owned. A trace with the call's ID that arrives after an earlier try of the evaluation links on the next try.
  - One owner row for each trace, written once: a later span belongs to the owner through its trace ID.
  - A call that links a trace sets `traces_linked_at` on its agent.
- **Clock lag.** The smallest difference between a span's arrival at Yaksh and its end on the agent's clock. With a correct clock it is the export delay.
- **Alignment.** Each gap of up to 60 s (2 s for a number link) between an agent speech start and a speech start that Yaksh heard is tried. The score of a gap is the number of agent starts within 250 ms of a Yaksh start, one to one. The best gap counts when it aligns 2 starts or more (1 when the agent has only 1, and for a number link, the recording too), and more starts than each gap more than 1 s away. The offset is the median gap of the aligned starts. Yaksh does not align a reading with more than 2,000 agent speech starts: that is more than one each 2 s of a 1-hour call.
- **Readers.** One for each framework gives the agent's speech starts and, for each reply, the agent's total and its parts on the agent's clock. A missing span or value makes a reply incomplete, never 0 ms.
  - LiveKit Agents 1.8: a reply is the first agent speech after the end of the caller's speech in a user turn. The total is `lk.e2e_latency` of the turn that speaks. When a tool hands the call to another agent, the new agent's turn speaks with no `lk.e2e_latency`. Then the total is the speech start less the end of the caller's speech by the user turn (its end less `lk.end_of_turn_delay`), the same point. A speech with no `lk.e2e_latency` is not a reply when no tool turn of this user turn comes before it: a tool turn that started before the user turn belongs to an earlier one. Parts: VAD endpointing, STT after VAD stop, turn detection, LLM TTFT and TTS TTFB after the end of the user turn, tool execution. LiveKit runs an end-of-turn check (`eou_detection`, a child of the user turn, or of its `eou_wait` span from 1.8.10) at the VAD's end of speech (`lk.eou.source` "vad"), and again when a later final transcript comes ("stt"). VAD endpointing ends at the start of the last VAD check after the end of the caller's speech, and STT after VAD stop runs from there to the last check. A turn with no VAD check takes the median VAD wait of the trace. A trace with no VAD check, as with no turn detector, gives one part, VAD and STT.
  - Pipecat 1.14: a reply is a turn span. The total is `turn.user_bot_latency_seconds`, and the speech start is the first TTS audio. The end of the caller's speech is the speech start less the total. The LLM requests of the reply are those that start after that end: when the caller speaks again after a pause, Pipecat cancels the request that it started in the pause. Parts: end of turn, LLM TTFT, tool execution (from the end of one LLM request to the next), sentence aggregation, TTS TTFB. No STT TTFS: Pipecat's STT TTFB is not one (0036).
  - The rest of the agent's total is Unattributed.
- **Pairing.** The eligible waits are the answered waits that start at the end of the caller's speech: no talk-over, no wait whose start moved to the end of the agent's speech, not the wait for the first speech of the call. Each wait pairs with the reply whose speech start, moved by the offset, is within 250 ms of Yaksh's. Network and telephony is Yaksh's wait less the agent's total; from -100 ms to 0 it is 0, below -100 ms the reply does not fit.
- **Metric.** `agent_reply_time`: the counts, the offset, the p50 and p90 of each part over the usable replies, the STT TTFS, and each paired reply, which the API also puts on its agent turn as `agent_reply`. With no parts it is a status: `no_traces` (only for an agent with `traces_linked_at`), `not_aligned`, `unknown_framework`, or `clock_off`.
- **`clock_off`.** When a call gets no trace, Yaksh takes the traces with the call's number, no owner, and a span that arrived after the connection. It moves each by its clock lag. Exactly one whose last span then ends within 5 s of the end of the call, with a clock lag beyond ±2 s, gives `clock_off` with that lag, also for an agent with no `traces_linked_at`. A trace with the call's ID that does not align gives `clock_off` when its lag is beyond ±60 s.
- **Cleanup.** Spans stay 7 days after they arrive, owner rows 7 days after the link. The evaluator deletes older ones every 10 minutes.

## Why

- The recording gives the wait but not its parts. The agent's own trace has the parts, and OTel is what LiveKit Agents and Pipecat already send.
- Linking at evaluation, not at arrival, is one rule for every framework: Pipecat sends its key last, and the alignment needs the recording.
- More than one trace for each call comes from a real call: the agent ended its session for a keypad step and started a new one. With one trace for each call, that call got no trace.
- The VAD split shows how much of the wait is the VAD's silence setting. In real traces the final transcript came before the VAD stop, so the STT added nothing.
- The number, the time and the alignment together are needed, because Yaksh uses a number again seconds after a call. The clock check stops a wrong clock that hides the time between two calls.
- A wrong clock is the most likely fault after setup, so the card shows its measured value.
- The handoff rule comes from real traces: without it, the slowest replies, those after a tool, had no parts.
- The Pipecat rules come from a real Pipecat 1.14 run. Its frames put the end of the caller's speech within 3 ms of the derived value. A cancelled request gave an end of turn of 0 ms, and the time of a tool went to Unattributed, before these rules.
- The remainder is taken before rounding: parts that fill the total exactly must not show as overlapping.
