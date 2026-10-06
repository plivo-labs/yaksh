# 0013 The caller closes the call before Yaksha hangs up

Date: 2026-10-01
Status: accepted

## Decision

When the caller ends the call, with end_call or with the goodbye at the turn limit, Yaksha does not hang up at once. It keeps the line open until one of these occurs:

- Both sides are quiet for 8 seconds. Quiet means that the agent is not speaking, and that no caller reply is being written, waits to be spoken, or has audio that Plivo has not reported played.
- The agent hangs up, a stop arrives, or the pipeline stops.
- 30 seconds pass.

While the line is open after end_call, the caller answers the agent. After the goodbye at the turn limit, the caller says nothing more. The caller gives no idle nudge in this time. The end reason stays `caller_hangup` or `turn_limit`, also when the agent hangs up first.

## Why

- The caller's last words play in full, and Plivo reports them played, so the transcript marks them transmitted. Before, Yaksha hung up when the pipeline had sent the audio, so the last words were often unconfirmed.
- How the agent closes a call is part of the test. The agent's goodbye or last offer is in the transcript and the recording.
- A real caller says goodbye, waits for the other side, and answers a last question.
- At the turn limit, an answer from the model goes back to the caller's goal, so the call does not end.

## Cost

- A call that the caller ends takes up to 8 seconds more. It takes up to 30 seconds when Plivo does not report the audio played or the agent continues to talk.
- The caller can call end_call again while the line is open. Only the first reason is kept.

## Other options

- Hang up when Plivo reports the last words played. Rejected: the hang-up cuts off the agent's reply.
- Wait a fixed time after the caller ends the call. Rejected: a short wait cuts off a long goodbye, and a long wait keeps a silent line open.
- Let the caller answer after the goodbye at the turn limit. Rejected: the model goes back to its goal, so the call does not end.
