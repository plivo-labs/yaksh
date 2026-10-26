## v0.5.1 (2026-10-26)

### Feat

- **conversation**: open calls with a small player and expand it on demand (#14)

### Fix

- **deps**: upgrade Pipecat to 1.14.0, Pillow to 13.0.0 and pypdf to 6.21.2 (#16)
  - Pillow and pypdf get their security fixes. The image is smaller: 1.08 GB, from 1.16 GB.
  - When the caller's model gives a phone reply with no words and no tool call, the conversation is now invalid, and Yaksh retries it within the run's retries. Before, the caller stayed silent and the call counted.
  - The end-of-turn model runs on onnxruntime 1.31. A few decisions on when the agent's turn ends can differ: 10 of 332 in a test on real calls, in both directions.
  - The caller's words in the transcript stay in step with its ElevenLabs audio after a punctuation mark.
- **console**: free recording audio and keep the search box in step with the address (#15)

## v0.5.0 (2026-10-25)

### Fix

- **caller**: stop the caller from ending calls before its instructions are done (#13)
  - The caller ends a call only when its instructions name the point or are done, and the agent's latest turn shows that point. Most calls now end when the agent ends them.
  - With no reasoning effort set, the caller uses `low`, or the model's lowest effort when that is higher. A model that Yaksh does not know gets no effort. To get the earlier behavior, set the caller's effort on Settings.

## v0.4.0 (2026-10-25)

### Feat

- **suites**: run several agents together and get one result (#12)
  - A suite is a saved list of agents, each with its connection (phone or text), scenarios and run settings. "Run suite" starts one run for each agent, and the suite run passes only when every run passes at the suite's required pass rate.
  - `yaksh suite run <id> --wait` waits for the result and exits 0 only on a pass, for use in CI.
  - In the console: a Suites page, a suite run page with live progress, and "Add to suite" on a run page.

## v0.3.0 (2026-10-24)

### Feat

- **agents**: read the agent's own record of a phone test and check it (#11)

### Changed

- The API applies database migration 0003 when it starts. It adds `agents.record_source`, `conversations.trigger_response`, `conversations.clock_started_at` and the `agent_records` table.
- A judge answer with a field that its schema does not allow is asked again, and then counts as invalid evidence. A model in strict mode never sends such an answer.
- The results view shows only the reasoning of a judge answer that failed the code checks, under the error.
- The conversation's details panel opens at 500 px, so that its six tabs fit.

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
