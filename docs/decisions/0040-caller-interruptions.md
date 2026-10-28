# 0040 Caller interruptions

Date: 2026-10-28
Status: accepted. Changes 0019 (an interruption line is not a caller reply) and 0036 (an interruption line is a source of its own).

## Decision

A scenario can hold up to 3 interruptions. Each one is a fixed line that Yaksh's caller says while the agent still speaks. Lines play on phone calls, while the persona is on the call.

- A start is each time the agent says the line's phrase (`agent_says`). For a line with no phrase, a start is the start of each answer from `from_answer` on. A start opens a wait of `after_s`.
- The line plays when the wait ends with the agent still speaking. A line with a phrase plays in the turn of the phrase. A line with no phrase plays in the turn of its answer that is open then.
- An answer starts after the persona's reply audio went out or after a key press, not at each Pipecat turn.
- The speech of each line is made with the persona's voice when the call starts. In process mode it goes to the call's process with the persona's own greeting, by its place in the list.
- `caller/interruptions.py` holds three parts:
  - The `Interrupter`, before the turn aggregator, reads the agent's words, its turns and the voice detector. It plays a line through the `SoundPlayer`.
  - The `LineGate`, after the stored agent turns, drops the agent's cut while a line plays. It also drops the persona's context frames until the speech that the lines interrupted is decided. That speech is each agent turn that starts before the latest line has played.
  - The `TurnOrder` keeps the transcript's turns in start order around a line.
- Each line gets its note in the persona's context after the turn that it interrupted. When the latest line has played and no agent turn is open, the last line decides what the persona does next:
  - The agent stopped within 2 s of the line's first sound and said nothing more in that speech: the persona waits for the agent. The next agent turn in which the agent speaks gets the reply. When 3 s pass with no agent turn open, the persona continues the call.
  - The agent stopped and then spoke again in that speech: the persona answers it.
  - Every other case: the persona answers the speech as usual.
- A stop is a quiet of the agent's voice of at least 0.6 s, the VAD stop of the measurement after the call. A quiet at the end of the agent's last turn becomes a stop when it lasts 0.6 s, and the gate waits for that.
- A line plays only after each cut of the agent's that passed the gate before it has reached the end of the pipeline. After 1 s, it plays anyway.
- Each try is a wire event of the kind `interruption`, with a typed field. A played line's try is saved when the line starts. It keeps the agent's words before the line, the start of its turn and the end of its 2 s window.
- The judges' view adds a sentence in parentheses after each interruption line: how far into which agent turn the caller spoke, and after which words. The CALLER part of the view lists the lines that played, as part of the caller's test.
- The lines count in the caller's speech, but in no wait for the agent's answer.
- This version decides no verdict on the agent's stop, and the field has no `expect` and no `within_s`.

## Why

- The caller spoke only after the agent's turn ended. So Yaksh could not test whether an agent stops when a caller talks over it.
- A line made before the call plays on time and says the same words in each run. A reply of the persona's model would come late and change from run to run.
- Answers, not turns: turn detection can split one greeting into two turns. A count of turns would then play a line in the rest of the greeting.
- Pipecat cuts the caller when a new agent turn starts. Also, the persona's model answers each agent turn, also the turn that a line still interrupts. The gate prevents both.
- The persona did not choose its line, so its model learns from a note that it said it. Replays of the persona's real requests chose each note's wording. With no note, a "Sorry, one moment." line made the persona wait as long as the agent did.
- With a VAD stop of 0.3 s, the agent's speech before it reacts to a line is often two turns. An example is the end of a sentence and the start of the next one. A decision at the end of the first turn made the persona answer the second turn while the agent prepared its answer to the line.
- A stop of 0.6 s keeps the meaning of a stop when the live VAD stop changes. A later measurement from the recording uses the same stop.
- Turn detection can end a turn in a pause of 0.4 s between two sentences. A decision at that moment told the persona that the agent stopped. The gate now waits until the quiet lasts 0.6 s.
- A persona that waits answers only the agent's voice. Late words of the cut speech made the persona reply, and the agent's real answer then got a second reply.
- On real calls, a cut from an agent turn that started 0.2 s before a line was still on its way when the line started. It took the line's words in the transcript, so the line showed twice. Such a cut can also drop the line's audio.
- The caller check judges the caller against its test. A caller that follows a line can break its known facts, and the check then blocks criteria that the agent failed. In replays of the caller check on one such call, it blocked them in 4 of 16 runs with no list. It blocked them in 0 of 16 runs with the list.
- No verdict yet: a fair verdict needs the agent's stop from the recording and an end-of-turn verdict at that stop. Neither is built yet. A setting that names a check that does not exist would mislead.

## Cost

- The persona's behavior after a line rests on note wordings that were tested with one caller model. Another model can read them differently.
- Backchannel lines are not supported: the gate treats every line as a line that the agent stops for.
- The persona keeps to its known facts. A line that gives another value does not change them, and the persona can take the value back later.
- The agent can talk over a line that asks it to wait and say later that it will wait. Then the persona gets no second note. It can wait until its question to a silent agent, 15 s later.
- A phrase needs a speech-to-text provider that gives the agent's words while it speaks. The run start refuses a phrase with Sarvam.
- The interrupted turn stays whole, so the transcript shows the line after it. The sentence after the line tells the judges where the line came.
- An older process refuses a scenario with interruptions and the new wire event kind. Add interruptions to a scenario only after every process runs this version.

## Other options

- Let the persona's model say the line when the start comes. Rejected: it comes late, and the words change from run to run.
- Split the agent's turn at the line in the transcript. Rejected: phrase rules and the judges read whole turns.
- Count Pipecat turns for `from_answer`. Rejected: a split greeting would take a line meant for the second answer.
- Give the judges a rule about interruptions. Rejected: the judges get the facts in the view and judge the call as any other call.
- Decide pass or fail on the agent's stop in this version. Put off to a later version: the measurement from the recording and the end-of-turn verdict are not built yet.
