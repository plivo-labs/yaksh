# 0017 Measure the agent's response time at Truman's connection

Date: 2026-10-04
Status: accepted

## Decision

Right after each call, Truman measures how long the agent made the caller wait:

- Each caller reply gets the first agent speech that starts after the reply began and before the next reply begins. The response time runs from the end of the caller's reply to the start of that speech. Before the caller has spoken, the call's start counts as a reply that began and ended when the call connected: when its audio started (decision 0016).
- When that speech starts before the caller's reply ended, the agent spoke over the caller. The reply has no response time and counts as a talk-over. A reply that the end of the call cut off has no end, so it has no response time either.
- A caller reply that the agent did not answer before the caller spoke again has no response time. The percentiles leave that wait out; the transcript shows it as the caller's next turn, often the idle nudge.
- The caller's reply runs from Pipecat's `BotStartedSpeakingFrame` to its `BotStoppedSpeakingFrame`: the `caller_audio_start` and `caller_audio_end` wire events, when Truman sends the audio.
- The agent's speech starts where Pipecat's `SileroVADAnalyzer`, with the live pipeline's settings, turns to speaking on the agent channel of the recording, less the windows it needs to decide. The recording places the agent's audio by Plivo's timestamps (decision 0015). Speech already under way when the recording starts begins at the connect; it answers the call's start with no value, as its true start is unknown.
- A call keeps each reply's two times and its p50 and p90, nearest rank, in its transcript. A run pools the replies of its latest attempts.

## Why

- One rule for every reply, including the first one, and for every transport. A test over a websocket later changes only how the recording places the agent's audio.
- It is the measuring point of the tools that test agents from a recording, such as Cekura and egma.
- Truman sent the caller's audio, so it knows when the reply ended. A voice detector on the caller channel would take background noise with voices for the caller.
- The transcript's agent turns start late: they are timed when the live pipeline reaches them, after speech to text. In the stored calls they started a median 421 ms after the agent's first audio. The recording's own speech starts keep pipeline delays out of the number.
- A loudness rule takes a quiet "thinking" sound for the reply. Silero did not take it for speech in any of 87 stretches of such sound on 12 recordings.
- A negative value for a talk-over would pull the p50 down and hide slow replies.

## Cost

- The number includes the path between Truman and the agent's system, both ways. For a phone call, that is about 0.2 s to Plivo through a tunnel, plus the phone path to the agent. A Truman far from Plivo reports a slower agent.
- In a call where the agent speaks first, the first value counts from the call's first audio, about 0.3 s after Plivo reports the answer (decision 0016), so it reads that much low. An agent already speaking when the call's audio starts gets no value for that reply.
- A spoken filler such as "hmm" counts as the agent's first speech. Hold music with a voice would too.
- An agent that does not answer leaves no value, so a silent agent does not raise the p90. Its silence shows in the transcript as the caller's idle nudge.
- Silero takes about 0.65 s of CPU for a 3-minute call.
- Pipecat's detector treats a window it cannot analyze as silence and logs the error.

## Other options

- Plivo's edge: date Plivo's `playedStream` report by the media frame before it, so both ends are on Plivo's clock. Rejected for now: it removes the path to Plivo, but works only for phone calls.
- The agent platform's own numbers (LiveKit, Pipecat, Retell). Rejected: they leave out the network, and Truman cannot read them for an agent on another platform.
- A voice detector on both channels, as Cekura does. Rejected: background noise on the caller channel.
- The transcript's turn times. Rejected: late by the pipeline's delays.
- A separate greeting time. Rejected: the start of the call already works as a reply with no caller speech.
