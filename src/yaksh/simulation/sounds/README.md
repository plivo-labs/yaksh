# Surroundings sounds

The sounds that play behind the caller in a test call: noise loops in this folder, and background speaker clips in `speakers/`. `simulation/surroundings.py` plans them, and `tests/simulation/test_surroundings.py` checks the rules below.

## Noise loops

### Rules

- WAV, 16-bit PCM, mono, 8000 Hz: the format of the phone leg. A call with a sound file in another format fails before it is placed.
- A whole number of 20 ms chunks (160 samples).
- RMS level -25 dBFS ± 0.5 dB, and peaks at or below -3 dBFS. A sound's gain in a call comes from this RMS level and the dB level the persona sets.
- No click and no jump in level where the loop starts again.

### How the files were made

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

## Speaker clips

`speakers.yaml` lists each clip: its language (`en` or `hi`), its kind (`talks_to_caller`, `own_phone_call` or `tv`), the ElevenLabs voice, the lines with their tone tags, the pauses between the lines, its length and the start time of each line.

### Rules

- WAV, 16-bit PCM, mono, 8000 Hz, a whole number of 20 ms chunks, as the noise loops.
- Active speech at -20 dBFS ± 0.5 dB, the caller's speech level, so 0 dB in a persona puts the speaker as loud as the caller. Peaks at or below -3 dBFS.
- The voices are not voices of the built-in personas, so the agent cannot tell the two people apart by the voice that it knows.

### How the files were made

`scripts/make_speaker_clips.py` builds every clip from `speakers.yaml` (2026-10-07): ElevenLabs `eleven_v3` speaks each line on its own, the lines are joined with the pauses, a light room effect is added (ffmpeg `highpass=f=100,lowpass=f=3600,aecho=0.9:0.9:30:0.12`), the speech level is set to -20 dBFS, and the peaks are limited to -3 dBFS. The script writes the length and the line start times back to `speakers.yaml`.

## Voicemail and call screener lines

`answering.yaml` lists the lines that the persona's voicemail or call screener plays, each with the voice of its phone system, and `answering/` holds one file for each line, plus `tone.wav`. `simulation/answering.py` puts them in a call's plan, and `tests/simulation/test_answering.py` checks the rules below.

### Rules

- WAV, 16-bit PCM, mono, 8000 Hz, a whole number of 20 ms chunks, as the noise loops.
- Active speech at -20 dBFS, the caller's speech level, with peaks at or below -3 dBFS.
- The tone is a 440 Hz sine, 1 s long, with a -6 dBFS peak and a 10 ms fade at each end.

### How the files were made

`scripts/make_answering_clips.py` builds every file from `answering.yaml` (2026-10-23): ElevenLabs `eleven_flash_v2_5` speaks each line at 8 kHz with stability 0.8, as the voice previews do, and the speech level is set to -20 dBFS. The script writes the tone without ElevenLabs. Lines that no real phone was recorded for are estimates.

## Terms

The sounds were generated with ElevenLabs, so the ElevenLabs terms of service apply to them.
