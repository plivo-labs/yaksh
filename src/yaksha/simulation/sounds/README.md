# Background noise sounds

Loops that play behind the caller in a test call. `simulation/background_noise.py` finds them, and `tests/simulation/test_background_noise.py` checks the rules below.

## Rules

- WAV, 16-bit PCM, mono, 8000 Hz: the format of the phone leg. Pipecat's `SoundfileMixer` skips a file with another sample rate, and it plays a stereo file at half speed.
- A whole number of 20 ms chunks (160 samples). At the end of a file, the mixer goes back to the first sample and skips a part chunk.
- RMS level -25 dBFS ± 0.5 dB, and peaks at or below -3 dBFS. The volume of each level depends on this RMS level.
- No click and no jump in level where the loop starts again.

## How the files were made

Each sound was generated on 2026-10-01 with the ElevenLabs sound effects API (`POST /v1/sound-generation`, 30 seconds, `prompt_influence` 0.5, `loop` true) from these prompts:

| File | Prompt |
| --- | --- |
| `street.wav` | busy city street ambience, passing cars and buses, distant car horns, people walking, steady background, no music |
| `cafe.wav` | busy cafe ambience, many people chatting indistinctly, cups and plates clinking, espresso machine hiss, no music |
| `office.wav` | open-plan office ambience, keyboards typing, a phone ringing in the distance, quiet indistinct conversations, air conditioning hum |
| `car.wav` | inside a moving car on a highway, steady road and engine noise, light wind noise, no music, no voices |
| `tv.wav` | a television playing in the next room, muffled indistinct talk show voices and audience laughter, quiet home ambience |
| `crowd.wav` | crowded train station hall, many people talking at once, footsteps, distant muffled announcements, echoing |
| `kitchen.wav` | home kitchen, dishes and cutlery clattering, running tap water, a child playing and talking in the background |
| `wind.wav` | windy outdoor park, wind gusts hitting the microphone, birds, distant traffic |

Then, for each file:

1. Resample from 44.1 kHz to 8 kHz as a closed loop: add one second from each end to the other end, resample, and cut the added seconds off again, so the join stays clean.
2. Set the RMS level to -25 dBFS.
3. Limit the peaks to -3.5 dBFS with ffmpeg's `alimiter` (attack 5 ms, release 50 ms), again as a closed loop, and set the RMS level again. Three passes.

The files are 30 s long (240,000 samples), except `crowd.wav`. Crowd is very even, and its level changed by 2.3 dB where the loop starts again. So its last second was mixed into its first second with an equal-power crossfade, and the RMS level set again. It is 29 s long (232,000 samples).

## Terms

The sounds were generated with ElevenLabs, so the ElevenLabs terms of service apply to them.
