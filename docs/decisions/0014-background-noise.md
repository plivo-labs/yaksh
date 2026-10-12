# 0014 Background noise is a persona setting that a call or a run can replace

Date: 2026-10-02
Status: replaced by 0027 (surroundings)

## Decision

- A persona has a background noise: a sound from a fixed list (none, street, cafe, office, car, TV, crowd, kitchen, wind) and a level (light, busy, loud). This extends the persona of decision 0006, how the caller behaves and sounds, and the setting is versioned with the persona.
- A run can replace the persona's setting for all its conversations. `{"sound": "none"}` means no noise; a missing or null value means the persona's setting.
- A conversation keeps the sound and the level it started with, and a retry copies them. When the call starts, the worker turns them into a file and a volume.
- Pipecat's `SoundfileMixer` mixes the noise into the caller's audio in the phone transport, under the voice and in every pause.
- The levels are signal-to-noise ratios of about 20, 10 and 5 dB against the measured speech level of the built-in voices, -20 dBFS. Every sound file has an RMS level of -25 dBFS, so the volumes are 0.178, 0.562 and 1.0.
- The sound files ship in the package.
- If the run override of persona settings is built (form 2 of `docs/ideas/run-persona-matrix.md`), it replaces the run's background noise field.

## Why

- Noise says where the caller is, as the voice says who the caller is. A replacement on a run compares the same scenarios with and without noise, with no copies of personas.
- The transport's mixer also fills the caller's pauses. Its noise-only frames make no speech events, so turn timing, wire events and the idle nudge do not change.
- Fixed levels make runs comparable.
- The persona model is not told about the noise, so a run with noise and a run without it differ only in the audio.

## Cost

- Yaksh sends audio for the whole call: 50 messages a second, also in the pauses.
- A missing or broken sound file fails the conversation, with the reason.

## Other options

- Noise on the scenario. Rejected: the scenario says what the caller wants, not where the caller is.
- A free volume or ratio. Rejected for now: presets are easier to compare.
- Mixing in Yaksh's pipeline before the transport. Rejected: the noise would stop between replies, and noise frames would count as caller speech.
