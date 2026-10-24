## v0.2.0 (2026-10-24)

### Feat

- **runs**: test voicemail and call screening on outbound phone runs (#10)

### Changed

- Run verdicts: `pending` and `not_judged` count all calls of the run, also the calls in the new `unplayed` list, where no caller talked.
- The API applies database migration 0002 when it starts.

## v0.1.2 (2026-10-23)

### Perf

- **caller**: share the VAD and end-of-turn model sessions across calls (#9)

### Changed

- **deps**: upgrade Pipecat to 1.13.0 (#8). For the same audio, a response time measured with this version is about 65 ms shorter than before, because its VAD (Silero v6.2, with new model resets) finds the end of speech later. Compare runs made with the same version.
- With no reasoning effort set, the caller sends the lowest effort that Pipecat lists for the model. `gpt-5`, `gpt-5-mini` and `gpt-5-nano` change from `none` to `minimal`; o-series models and `gpt-6-astra` change from the model's default to `low`. The default caller model does not change.

## v0.1.1 (2026-10-22)

### Feat

- **settings**: set the worker's conversation limits on the Settings page (#7)

### Fix

- **release**: let GoReleaser read the release notes file (#6)

## v0.1.0 (2026-10-19)

The first public release.
