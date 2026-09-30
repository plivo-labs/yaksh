# Background noise in test calls

## Problem

Truman's caller speaks with no sound behind it. Real callers phone from streets, cars, cafes and offices. Noise changes what the agent hears: its speech-to-text makes more errors, and its voice activity detection can take noise for speech. The agent then stops talking for nothing (a false barge-in) or waits too long for the end of a turn. Truman tests none of this today.

## Today

- The caller's audio is the synthesized voice only.
- Pipecat's output transport mixes background audio into what it sends when `audio_out_mixer` is set. It mixes the background into each speech frame, and it sends background-only frames while the caller is quiet, so the noise runs through the whole call (`pipecat/transports/base_output.py`, `with_mixer`).
- `SoundfileMixer` loops a sound file at a set volume, can change the file or the volume during a call (`MixerUpdateSettingsFrame`), and skips a file whose sample rate is not the transport's (8 kHz on the phone path).

## Idea

1. A noise setting when a conversation starts: a background (none, street, cafe, office, car, TV, crowd) and a level.
2. The worker passes a `SoundfileMixer` as `audio_out_mixer` in the phone transport parameters (`caller/phone.py`), with the chosen file as 8 kHz mono.
3. The level is a signal-to-noise ratio (for example 20 dB light, 10 dB busy, 5 dB loud). The mixer only applies a fixed volume and clips the sum, so the conversion needs the measured levels of the voice and the noise file, and headroom so the mix does not clip.
4. Truman ships a small set of background files under a license that permits it, and accepts the user's own file.
5. The conversation page shows the noise setting, so a conversation with noise and the same one without it can be compared.

Later: short sound events at random times (a door, a dog, a cough) to test false barge-ins. The mixer can change files during a call.

## Rules

- The recording holds what was sent, noise included. The recorder sits after the output transport. Check that it gets the mixed frames.
- Noise-only frames fill every moment the output queue is empty, also inside a reply. Checkpoints stay tied to the speech pieces; check their timing with a barge-in call.
- Noise goes only into the audio Truman sends. The caller's own speech-to-text hears only the agent.

## Size

About a day for one background at one level, without the UI. About one more day for the setting in the UI and the files.

## Open questions

- Is noise part of the persona (where the caller is) or an option when a conversation starts? An option at start makes a clean comparison with and without noise.
- Which background files, and under which license?
- Line problems (packet loss, low bit rate, echo) need a different mechanism than a mixer. A separate idea?
