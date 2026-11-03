# 0043 Agent stop time after an interruption line

Date: 2026-11-03
Status: accepted. Changes 0040 (an interruption line now has a stop time, and the judges see it). Builds on 0019 (the measurement after the call).

## Decision

After each phone call, Yaksh measures when the agent's speech stopped after each interruption line that played. It uses only what the call stores: the recording, each reply's own audio, and the agent's media record.

- **Start.** The start of the first speech in the line's own audio (S). The silence that the TTS puts before the first word does not count.
- **End.** The end of the agent's speech, from the measurement after the call, that holds S: its start ≤ S < its end (E). The stop time is E − S.
- **Heard.** Yaksh heard the agent's channel at a moment that is in the agent's media, before the end of the recording and in no media gap. The recording fills the other times with silence, and that silence is no quiet of the agent.
- **Confirmed stop.** Yaksh heard the whole time from E to E + 0.6 s, the VAD stop of the measurement.
- **Results**, in this order:
  1. `unknown`, `no_line_speech`: the part of the line that went out has no speech.
  2. `unknown`, `media_gap`: Yaksh did not hear S.
  3. `not_speaking`: no agent speech holds S.
  4. `kept_talking`: E − S > 2 s. With no confirmed stop, `at_least` is true, with the reason `recording_ended` or `media_gap`.
  5. `not_speaking`: E − S < 200 ms and a confirmed stop: the speech was ending by itself.
  6. `stopped`: E − S ≤ 2 s and a confirmed stop.
  7. `unknown`: E − S ≤ 2 s and no confirmed stop, with the reason `recording_ended` or `media_gap`.
- The metric `stop_time` keeps each line's result, the count of each result, and the p50 and p90 (nearest rank) of the `stopped` lines. A `kept_talking` line raises the flag `kept_talking`.
- The run metrics pool the `stopped` lines of the calls, count the lines, and give the share of calls with a `kept_talking` line, of the calls with a `stopped` or `kept_talking` line.
- The API puts each line's result on the first turn of the line, as `agent_stop`.
- The judges' view adds a sentence in whole ms after the note of each line, and states an `unknown` result with its reason. The view version is 11. The criterion, agent rule and instructions judges are told not to quote a note, and to quote the agent turn that it names.

## Why

- A scenario can test if an agent stops when a caller talks over it, but nothing measured the stop. The live check only decides what the persona does next.
- The stored data is enough, so the measurement needs no new capture. The time from the line's speech start to the end of the agent's speech is what the caller hears. Other testers that use audio measure the same points.
- The 2 s and the 0.6 s are the values of the live check, so the two agree on most calls. They are not the same rule: the live window starts when the line starts to play, and it ignores a quiet that the agent's voice ends while the line plays.
- Silence in the recording can be missing media. Without the heard quiet, an agent stream that dropped looks like a fast stop.
- Speech that Yaksh heard for more than 2 s shows that the agent kept talking, also when a gap or the end of the recording comes later.
- An agent cannot stop for a line sooner than the line reaches it and its VAD hears it. On real calls, a stop 3 ms after a line's start was speech that ended by itself. The fastest stop that the agent's own record showed as an interruption was 337 ms. Thus a stop under 200 ms is no stop for the line.
- Whole ms let a judge compare the time with a limit in a criterion. A rounded 0.8 s can pass a limit of 800 ms that 841 ms fails.
- One line can be two turns: the part that went out and the part that did not. The result and the judges' note go on the first.

## Cost

- The stop time does not tell why the speech stopped. A turn that ends by itself 200 ms to 2 s after the line starts gets `stopped`, and so does an agent that stops and then continues the same reply. An end-of-turn model on the agent's audio did not separate these cases.
- The time includes the network in both directions and the agent's audio buffers. It is not the agent's own reaction time.
- An echo of the caller on the agent's channel counts as agent speech.
- The percentiles leave out the lines where the agent kept talking. Their count shows them.
- Calls evaluated before this change have no stop time.

## Other options

- A pass or fail for each line, with a time limit. Rejected for now: a criterion can use the time that the judges see, and a code verdict needs a way to find a turn that ended by itself.
- The time from the agent's own record. Rejected: a record logs a cut turn when the agent's code handles it, about 1 s after the audio stopped.
- An end-of-turn model to find a turn that ended by itself. Rejected: on the agent's phone audio it called most cut speech "complete".
- Measure from the start of the line's audio. Rejected: the TTS silence before the first word, 0.1 to 0.2 s, is not caller speech.
