# 0027 A persona's surroundings: noise and a background speaker, planned before each call

Date: 2026-10-07
Status: accepted

## Decision

- A persona has `surroundings`: noise `sounds` (each noise loop at its own level), or `auto` noise, and an optional `speaker`, a person who talks behind the caller. Every level is in dB relative to the caller's speech, so 0 dB is as loud as the caller. This replaces the background noise of decision 0014.
- A run has no noise setting of its own. To compare a quiet and a noisy test, use two personas.
- When a run creates a conversation, Yaksh turns the surroundings into a sound plan: each sound file with its gain, start, end, and whether it loops. The conversation keeps the plan, and a retry copies it. The worker's mixer only adds the plan's layers to the caller's audio.
- The random parts (auto noise and the order of the speaker's clips) come from a key of the scenario version and the repeat number, plus the auto noise seed. The same scenario and repeat in a new run play the same sounds, so a fix can be checked under the same conditions. Two repeats in one run differ.
- The speaker's clips are recorded once with ElevenLabs and ship in `src/yaksh/simulation/sounds/speakers/`. A call needs no extra key, costs nothing more, and plays the same audio each time. There are English (`en`) and Hindi (`hi`) clips, one set per persona language.
- The persona form previews the surroundings in the browser: the server returns the plan, and the browser adds the files together with the same gains.

## Why

The plan is decided before the call, so the call page can show when each sound played and what the speaker said, and a rerun can repeat it. A plan with clear times is also easier to test than random choices during the call.

The judges get no information about the surroundings. When the agent acts on the background speaker, the scenario's criteria fail; the call page shows the reason.
