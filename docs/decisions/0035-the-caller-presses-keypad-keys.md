# 0035 The caller presses keypad keys

Date: 2026-10-26
Status: accepted

## Decision

On a phone call, the caller's model has a second tool, `press_keys`, beside `end_call`. When the agent asks the caller to type or enter something on the phone keypad, the model calls it with the keys and says nothing in that reply.

- Yaksh drops spaces and dashes and pushes the keys as Pipecat's `OutputDTMFUrgentFrame`. A processor in `conversation.py`, right before the transport output next to the checkpoints, turns it into one audio stream message to Plivo, `{"event": "sendDTMF", "dtmf": "<keys>"}`, so the frame never reaches the transport. Both are urgent frames, so the agent talking over the caller does not drop the press.
- Keys other than 0 to 9, `*` and `#`, or no keys at all, press nothing: `OutputDTMFUrgentFrame.from_string` raises `ValueError` for them. The tool result says why, and Pipecat runs the model again (`run_llm=True`).
- The press is a caller turn with `dtmf: true`, at the time of the press. The evidence view marks it "pressed on the phone keypad, not spoken", the heard check skips it, and the console shows a DTMF badge.
- A reply that only presses keys makes no sound, so Pipecat never starts its idle timer, which starts when the caller stops speaking. When the press's result reaches the user aggregator, Yaksh starts that timer again with `wait_for_agent`, as after a reply with no words, so the same nudge and give-up follow as after speech. Pipecat keeps the timer off while it counts a function call as running, and the count drops only when the result frame reaches the aggregator, after the tool handler has returned, so a start from the handler itself does nothing.
- A text call has no keypad and does not get the tool.

## Why

- Agents take card numbers, PINs and account numbers on the keypad: "enter your card number, followed by the pound key". A caller that can only speak cannot test that path.
- Plivo's stream protocol takes DTMF on the websocket that carries the audio, and Yaksh's stream serializer already sends any transport message as JSON. No new connection is needed, and `conversation.py` makes this message with the other stream messages (`clearAudio`, `checkpoint`, `playAudio`).
- Judges quote numbered turns, so the press is a turn, not a wire event.

## Cost

- A reply that speaks and presses keys records the keypad turn at the press, before its spoken turn, which is recorded when its audio has played. The tool description and the caller prompt ask for no words in a reply that presses keys.
- Only the keys of a phone: Plivo also takes A to D.
- The model can send keys that are not on a keypad again; each try runs the model once more, until the call's time limit.

## Other options

- Pipecat's DTMF frame all the way to the transport output. Rejected: the websocket transport has no DTMF of its own, so Pipecat plays the keys as tones in the caller's audio instead of sending DTMF.
- The caller says the digits. Rejected: that does not test the agent's keypad path.
- A scenario field that turns the tool on. Rejected: the tool does nothing until the agent asks for keys.
