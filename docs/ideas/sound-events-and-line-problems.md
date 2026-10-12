# Sound events, own sound files and line problems

Background noise plays one looped sound behind the caller for the whole call (docs/decisions/0014). These are the parts of the first idea that are not built.

## Sound events

Short sounds at random times, such as a door, a dog or a cough, to test false barge-ins: the agent stops talking because it takes a sound for speech. Pipecat's mixer can change its file during a call with `MixerUpdateSettingsFrame`.

## Own sound files

A user adds a sound that Yaksh does not ship. The upload must turn the file into the format of the shipped sounds: 8 kHz 16-bit mono WAV at -25 dBFS RMS, a whole number of 20 ms chunks (`src/yaksh/simulation/sounds/README.md`). The file store that documents use can hold it.

## Line problems

Packet loss, a low bit rate and echo. A mixer cannot make them; they need a step that changes the caller's audio itself.

## Open questions

- Which of these do users ask for first?
- Line problems need a different mechanism than a mixer. A separate idea?
