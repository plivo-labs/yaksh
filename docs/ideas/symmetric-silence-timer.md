# Symmetric silence timer

## Problem

The caller's silence timer starts only when the caller stops speaking (Pipecat's `UserIdleController` arms on `BotStoppedSpeakingFrame`). When an agent turn ends and the caller does not speak after it, nothing starts the timer, and the call waits until its time limit. Two known cases:

- The agent makes a sound that speech-to-text returns no text for. Nothing to answer, so no reply.
- A late transcript starts a new agent turn that interrupts the caller's reply before its first word, and that turn has no new text.

## Production

LiveKit Agents 1.8 starts its away timer whenever both sides are quiet (`agent_session.py`, `_set_user_away_timer`), whoever spoke last. A sound with no text gets no reply (`audio_recognition.py`, `_run_eou_detection` returns early), and the timer covers it. When the timer fires, the agent reminds and then hangs up.

## Idea

Start the silence timer when both the agent and the caller are quiet, including at the end of an agent turn. On expiry, the caller nudges, and silence through every nudge ends the call, as today.

## Open question

After an agent turn that the caller never answered, should the caller nudge ("Hello?") or answer the turn? Production nudges.
