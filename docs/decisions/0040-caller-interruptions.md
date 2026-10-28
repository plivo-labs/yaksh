# 0040 Caller interruptions

Date: 2026-10-28
Status: accepted. Changes 0019 (an interruption line is not a caller reply) and 0036 (an interruption line is a source of its own).

## Decision

A scenario can hold up to 3 interruptions. Each one is a fixed line that Yaksh's caller says while the agent still speaks, on a phone call, while the persona is on the call.

- A start is each time the agent says the line's phrase (`agent_says`), or, for a line with no phrase, the start of each answer from `from_answer` on. A start opens a wait of `after_s`. The line plays when the wait ends with the agent still speaking: in the turn of the phrase, or, with no phrase, in the turn of the answer that is open then. An answer starts after the persona's reply audio went out or after a key press, not at each Pipecat turn.
- The speech of each line is made with the persona's voice when the call starts. In process mode it goes to the call's process with the persona's own greeting, by its place in the list.
- `caller/interruptions.py` holds three parts:
  - the `Interrupter`, before the turn aggregator, reads the agent's words, its turns and the voice detector, and plays a line through the `SoundPlayer`;
  - the `LineGate`, after the stored agent turns, drops the agent's cut while a line plays, and the persona's context frames until the turn that the lines interrupted ends. Then it writes a note for each line, and the last line decides what the persona does next;
  - the `TurnOrder` keeps the transcript's turns in start order around a line.
- The gate's three outcomes:
  - The agent stopped within 2 s of the line's first sound and said nothing more in that turn: the persona waits for the agent. The next agent turn with words gets its reply. When 3 s pass with no agent turn open, the persona continues the call.
  - The agent stopped and then spoke again in that turn: the persona answers that turn.
  - Every other case: the persona answers the turn as usual.
- A stop is a quiet of the agent's voice of at least 0.6 s, the VAD stop of the measurement after the call, or the quiet that the agent's turn ended in. The live VAD stop in Settings can be shorter, and a pause between two sentences is then no stop.
- Each try is a wire event of the kind `interruption`, with a typed field. A played line's try is saved when the line starts. It keeps the agent's words before the line, the start of its turn and the end of its 2 s window.
- The judges' view adds a sentence in parentheses after each interruption line: how far into which agent turn the caller spoke, and after which words. The CALLER part of the view lists the lines that played, as part of the caller's test.
- The lines count in the caller's speech, but in no wait for the agent's answer.
- This version decides no verdict on the agent's stop, and the field has no `expect` and no `within_s`.

## Why

- The caller spoke only after the agent's turn ended, so Yaksh could not test whether an agent stops when a caller talks over it.
- A line made before the call plays on time and says the same words in each run. A reply of the persona's model would come late and change from run to run.
- Answers, not turns: turn detection can split one greeting into two turns, and a count of turns would then play a line in the rest of the greeting.
- The gate is needed because Pipecat cuts the caller when a new agent turn starts, and because the persona's model answers each agent turn, also the turn that a line is still interrupting.
- The persona did not choose its line, so its model learns from a note that it said it. Replays of the persona's real requests chose each note's wording: with no note, a "Sorry, one moment." line made the persona wait as long as the agent did.
- The persona's wait ends only with an agent turn that has words, or with 3 s of no agent turn. A wait that ended at a fixed time made the persona reply a second time, or talk over the agent, when the agent's answer started during the line.
- A stop of 0.6 s keeps the meaning of a stop when the live VAD stop changes. It is also the stop that a later measurement from the recording uses.
- The caller check judges the caller against its test. Without the lines in that test, a caller that follows a line that asked for a new day breaks its known facts, and the check then blocks the criteria that the agent failed. In replays of the caller check on one such call, it blocked them in 4 of 16 runs with no list and in 0 of 16 runs with the list.
- No verdict yet: a fair verdict needs the agent's stop from the recording and an end-of-turn verdict at that stop, which are not built. A setting that names a check that does not exist would mislead.

## Cost

- The persona's behavior after a line rests on note wordings that were tested with one caller model. Another model can read them differently.
- Backchannel lines are not supported: the gate treats every line as a line that the agent stops for.
- When the agent talks over a line that asks it to wait and says later in the turn that it will wait, the persona gets no second note. It can wait until its question to a silent agent, 15 s later.
- A phrase needs a speech-to-text provider that gives the agent's words while it speaks. The run start refuses a phrase with Sarvam.
- The interrupted turn stays whole, so the transcript shows the line after it. The sentence after the line tells the judges where the line came.
- An older process refuses a scenario with interruptions and the new wire event kind. Add interruptions to a scenario only after every process runs this version.

## Other options

- Let the persona's model say the line when the start comes. Rejected: it comes late, and the words change from run to run.
- Split the agent's turn at the line in the transcript. Rejected: phrase rules and the judges read whole turns.
- Count Pipecat turns for `from_answer`. Rejected: a split greeting would take a line meant for the second answer.
- Give the judges a rule about interruptions. Rejected: the judges get the facts in the view and judge the call as any other call.
- Decide pass or fail on the agent's stop in this version. Put off to a later version: the measurement from the recording and the end-of-turn verdict are not built yet.
