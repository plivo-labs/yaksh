# 0040 Caller interruptions

Date: 2026-10-28
Status: accepted

## Decision

A scenario can hold up to 3 interruptions. Each one is a fixed line that Yaksh's caller says while the agent still speaks, on a phone call, while the persona is on the line.

- A start is each time the agent says the line's phrase (`agent_says`), or, for a line with no phrase, the agent's first speech in each answer from `from_answer` on. A start opens a wait of `after_s`. The line plays when the wait ends with the agent still speaking in the same turn. An answer starts after the persona's reply audio went out or after a key press, not at each Pipecat turn.
- The speech of each line is made with the persona's voice when the call starts. In process mode it goes to the call's process with the persona's own greeting, by its place in the list.
- `caller/interruptions.py` holds three parts:
  - the `Interrupter`, before the turn aggregator, reads the agent's words, its turns and the voice detector, and plays a line through the `SoundPlayer`;
  - the `LineGate`, after the stored agent turns, drops the agent's cut and the persona's context frames while a line plays. When the interrupted turn ends, it writes a note for each line, and the last line decides what the persona does next. If the agent's first stop came within 2 s of the line's first sound and the agent said nothing more in that turn, the persona waits for its answer, and goes on with the call after 3 s with no word. If the agent stopped and spoke again, the persona answers it. Otherwise the persona answers the turn as usual;
  - the `TurnOrder` keeps the transcript's turns in start order around a line.
- Each start's outcome is a wire event of the kind `interruption`, with a typed field. A played line's event keeps the agent's words before the line, the start of its turn and the end of its 2 s window.
- The judges' view adds one line after each interruption line: how far into which agent turn the caller spoke, and after which words. The lines count in the caller's speech, but in no wait for the agent's answer.
- This version decides no verdict on the agent's stop, and the field has no `expect` and no `within_s`.

## Why

- The caller spoke only after the agent's turn ended, so Yaksh could not test whether an agent stops when a caller talks over it.
- A line made before the call plays on time and says the same words in each run. A reply of the persona's model would come late and change from run to run.
- Answers, not turns: turn detection can split one greeting into two turns, and a count of turns would then play a line in the rest of the greeting.
- The gate is needed because Pipecat cuts the caller when a new agent turn starts, and because the persona's model answers each agent turn, also the turn that a line is still interrupting.
- The persona did not choose its line, so its model learns from a note that it said it. Replays of the persona's real requests chose each note's wording: with no note, a "Sorry, one moment." line made the persona wait as long as the agent did.
- No verdict yet: a fair verdict needs the agent's stop from the recording and an end-of-turn verdict at that stop, which are not built. A setting that names a check that does not exist would mislead.

## Cost

- The persona's behavior after a line rests on note wordings that were tested with one caller model. Another model can read them differently.
- Backchannel lines are not supported: the gate treats every line as a line that the agent stops for.
- A phrase needs a speech-to-text provider that gives the agent's words while it speaks. The run start refuses a phrase with Sarvam.
- The interrupted turn stays whole, so the transcript shows the line after it. The judges' line tells them where the line came.
- An older process refuses a scenario with interruptions and the new wire event kind. Add interruptions to a scenario only after every process runs this version.

## Other options

- Let the persona's model say the line when the start comes. Rejected: it comes late, and the words change from run to run.
- Split the agent's turn at the line in the transcript. Rejected: phrase rules and the judges read whole turns.
- Count Pipecat turns for `from_answer`. Rejected: a split greeting would take a line meant for the second answer.
- Decide pass or fail on the agent's stop in this version. Put off to a later version: the measurement from the recording and the end-of-turn verdict are not built yet.
