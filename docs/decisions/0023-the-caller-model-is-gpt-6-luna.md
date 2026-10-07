# 0023 The caller model is gpt-6-luna

Date: 2026-10-05
Status: accepted, changed by 0027 (the model is on the Settings page)

## Decision

The default caller model (`PERSONA_LLM_MODEL`) is `gpt-6-luna`, not `gpt-4.1`. Yaksha sets no reasoning effort for it, so Pipecat sends effort `none`.

## Why

- Over the Responses API, gpt-4.1 can return several assistant messages in one response. Each message is a full reply. Pipecat streams the text of all the messages into one reply, and the caller speaks all of them as one turn.
- In real calls, the caller said one line four or five times with small changes, answered questions that the agent had not asked, and spoke the agent's lines. One Hinglish turn ran for 106 s while the agent waited.
- On the eval rig, 12 of 120 Hinglish caller turns and 14 of 945 English caller turns had a repeated sentence. A repeated sentence is the visible symptom; a turn that runs ahead without a repeat is not counted.
- Replays of bad turns, with the same prompt and history, against the same Azure resource:

| Model | Responses with more than one message |
|---|---|
| gpt-4.1, worst turn | 12 of 12 |
| gpt-4.1, four bad turns (Hinglish and English) | 27 of 40 |
| gpt-6-luna, effort `none`, the same four turns | 0 of 40 |
| gpt-4.1-mini, worst turn | 0 of 12 |
| gpt-5.4-mini, effort `none`, worst turn | 0 of 12 |

- No prompt change that we tested stopped it. With gpt-4.1, a goal with no quoted lines still gave 10 of 12, and a rule "your reply is only your next turn" gave 11 of 12.
- The time to the first text, on the worst turn, 8 requests each: a median of 771 ms for gpt-6-luna and 789 ms for gpt-4.1.
- A live rerun of the five Hindi TeleCRM scenarios with gpt-6-luna had no repeated sentence in 34 caller turns.

## Cost

- Decision 0020 rejected a stronger caller model for its cost and a slower first word. The first word is not slower; each caller turn costs gpt-6-luna's price instead of gpt-4.1's.
- Scenario generation uses the persona model when `GENERATION_LLM_MODEL` is not set. gpt-6-luna takes `GENERATION_LLM_REASONING_EFFORT` (default `max`), which gpt-4.1 refused, so generation can take longer.
- An install that sets `PERSONA_LLM_MODEL=gpt-4.1` keeps the defect.

## Other options

- Go back to Chat Completions. Rejected: Yaksha calls every model through the Responses API, and that API returns one message by design, so it would only hide what the model does.
- Speak only the first message of a response. Not done yet: it would stop any model from doing this. With gpt-6-luna, no replay returned a second message.
- Change the caller prompt. Rejected: no prompt change that we tested stopped it.
