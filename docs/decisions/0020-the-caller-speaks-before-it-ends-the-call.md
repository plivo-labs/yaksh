# 0020 The caller speaks before it ends the call

Date: 2026-10-04
Status: accepted

## Decision

The caller's model ends a call with the `end_call` tool. A reply that calls `end_call` without any words does not end the call:

- The first time in a call, the tool result tells the model that the call did not end. It must answer the agent's latest turn aloud and say goodbye in the reply that calls `end_call`. Pipecat runs the model again (`run_llm=True`).
- The second time, Truman says the language's goodbye line, then ends the call.

The caller asks the model for one tool call at a time (`parallel_tool_calls: false`), so one reply cannot end the call twice.

## Why

- In a real call, gpt-4.1 answered the agent's "…Is that correct?" with only `end_call`. The line was silent for 10 s, and the question got no answer. The caller prompt already asked for a goodbye, but no code checked it.
- With the check, real calls had a silent `end_call` in 3 of 5 calls and then in 2 of 5 calls. After each refusal, the caller spoke before it ended the call, for example "Yes, that's correct… Okay, thanks. Bye." after "…Is that correct?".
- test-voice-agent asks its model for JSON with the spoken text and an end flag, and asks again once when the text is empty. Truman keeps the tool, because it streams the model's text into the TTS.
- Pipecat runs the tool handler on its own task, and a later reply can start before it runs. So the generated tap records, for each tool call, whether its reply had words when Pipecat starts the calls (`FunctionCallsStartedFrame`).

## Cost

- A model that ends without a word takes one more reply before the call ends.
- When the agent is speaking at the refusal, Pipecat does not run the model again. The agent's next turn runs it, with the note in the context. An agent turn with no words leaves the caller silent until the idle nudge.
- One retry for each call. A later silent `end_call` in the same call gets the fixed goodbye at once.

## Other options

- JSON replies with the spoken text and an end flag, as in test-voice-agent. Rejected: each reply would wait for the whole JSON object before the TTS starts.
- Say the fixed goodbye at once. Rejected: the agent's last question still gets no answer.
- A stronger caller model. Rejected for now: more cost and a slower first word on every turn.
