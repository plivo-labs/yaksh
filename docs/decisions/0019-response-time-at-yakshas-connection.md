# 0019 Measure the agent's response time at Yaksha's connection

Date: 2026-10-04
Status: accepted

## Decision

After each call is saved, the evaluator (decision 0022) measures how long the agent made the caller wait:

- Each caller reply gets the first agent speech that starts after the reply began and before the next reply begins. The response time runs from the end of the caller's speech to the start of that speech. Before the caller has spoken, the call's start counts as a reply that ended when Yaksha's stream opened. The agent's first speech answers it. Speech that started by then was under way: it gets no value, as its true start is unknown.
- When that speech starts before the caller's reply ended, the agent spoke over the caller. The reply has no response time and counts as a talk-over. A reply that the end of the call cut off has no end, so it has no response time either.
- A caller reply that the agent did not answer before the caller spoke again has no response time. The percentiles leave that wait out; the transcript shows it as the caller's next turn, often the idle nudge.
- A wait that overlaps a gap in the agent's media gets no value. In a gap, no audio came from the line, so the line and not the agent can have made the wait longer.
- When the agent was still speaking after the caller's speech ended, the wait starts where that speech ends: until then, the caller did not wait in silence.
- Only replies that expect an answer get a value: not the caller's goodbye, and not the start of a call that Yaksha's caller opens.
- The caller's reply starts at Pipecat's `BotStartedSpeakingFrame`, the `caller_audio_start` wire event. Its speech ends where Pipecat's `SileroVADAnalyzer`, with the live pipeline's settings, last finds speech in the reply's own TTS audio, before Yaksha mixes in background noise. Yaksha counts that point back from the `BotStoppedSpeakingFrame`, the `caller_audio_end` wire event, when the last audio went out. A reply cut off before its TTS finished keeps the `caller_audio_end` time.
- The agent's speech starts where the same analyzer turns to speaking on the agent channel of the recording, less the windows it needs to decide. The recording places the agent's audio by Plivo's timestamps (decision 0015).
- Each analyzer first hears 0.4 s of silence. Pipecat's volume reads 0 until it holds 0.4 s of audio, so without that silence the analyzer cannot hear the first 0.4 s. Before its first sample, each channel held nothing.
- A call keeps each reply's two times and its p50 and p90, nearest rank, in its `response_time` metric. A run pools the replies of its latest attempts.

## Why

- One rule for every reply, including the first one, and for every transport. A test over a websocket later changes only how the recording places the agent's audio.
- It is the measuring point of the tools that test agents from a recording, such as Cekura and egma.
- Yaksha sent the caller's audio, so it knows when the reply ended. A voice detector on the caller channel would take background noise with voices for the caller: on the mixed channel, kitchen noise moved the end of speech by up to 256 ms.
- The TTS ends each reply with 0.03 to 0.35 s of quiet audio. Counted from the last audio sent, the values read short by that much. On 4 stored replies, the end from the reply's own audio gave values within 23 ms of the gap between the caller's last word and the agent's first word: the analyzer finds both about 45 ms late, so the two errors cancel. On a real call, a reply read 2208 ms against a gap of 2220 ms.
- When the agent speaks first on a phone call, Plivo stamps its first frame about 0.8 s before Yaksha's stream opens (decision 0016). In 3 calls, the agent's speech started within 40 ms of that frame. Counted from that frame, the call's start got the TTS's quiet start plus the analyzer's warm-up, not a wait: 544 ms in 2 calls. A real call with the stream opening as the start got no value for the call's start, which is correct.
- The transcript's agent turns start late: they are timed when the live pipeline reaches them, after speech to text. In the stored calls they started a median 421 ms after the agent's first audio. The recording's own speech starts keep pipeline delays out of the number.
- A loudness rule takes a quiet "thinking" sound for the reply. Silero did not take it for speech in any of 87 stretches of such sound on 12 recordings.
- A negative value for a talk-over would pull the p50 down and hide slow replies.

## Cost

- The number includes the path between Yaksha and the agent's system, both ways. For a phone call, that is about 0.2 s to Plivo through a tunnel, plus the phone path to the agent. A Yaksha far from Plivo reports a slower agent.
- In a phone call where the agent speaks first, its speech usually starts before Yaksha's stream opens, so the call's start gets no value. Yaksha cannot see when the agent heard the call.
- At the start of a channel, Pipecat's volume needs about 0.16 s to rise from 0. Speech in the first 0.2 s of the agent channel starts that much late. This matters only for an agent that starts to speak within 0.2 s of the stream opening, with no frames before it.
- A reply cut off before its TTS finished keeps the time its last audio went out, so its value reads short by the TTS's quiet tail.
- Yaksha keeps the TTS audio of each reply until the call ends, then saves it next to the recording: 16 kB for each second of speech.
- A spoken filler such as "hmm" counts as the agent's first speech. Hold music with a voice would too.
- An agent that does not answer leaves no value, so a silent agent does not raise the p90. Its silence shows in the transcript as the caller's idle nudge.
- Silero takes about 0.65 s of CPU for a 3-minute call.
- Pipecat's detector resets Silero's state every 5 s of clock time. Live, that is every 5 s of audio. The evaluator analyzes a call much faster than real time, so the state resets about once for each call.
- Pipecat's detector treats a window it cannot analyze as silence and logs the error.

## Other options

- Plivo's edge: date Plivo's `playedStream` report by the media frame before it, so both ends are on Plivo's clock. Rejected for now: it removes the path to Plivo, but works only for phone calls.
- The agent platform's own numbers (LiveKit, Pipecat, Retell). Rejected: they leave out the network, and Yaksha cannot read them for an agent on another platform.
- A voice detector on both channels, as Cekura does. Rejected: background noise on the caller channel.
- The transcript's turn times. Rejected: late by the pipeline's delays.
- A separate greeting time. Rejected: the start of the call already works as a reply with no caller speech.
- Count the call's start from the `connected` wire event, the agent's first frame when it is earlier than the stream opening (decision 0016). Rejected: when the agent speaks first, that frame starts its greeting, so the value is the TTS's quiet start, not a wait.
- A fixed TTS tail for each voice. Rejected: the tail changed from 0.03 to 0.35 s between replies of one voice.
