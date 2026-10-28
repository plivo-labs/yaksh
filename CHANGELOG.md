## v0.9.2 (2026-10-28)

### Perf

- **caller**: send fewer input tokens in each caller request (#31)
  - Each request to the caller's model sends about 30% fewer input tokens, so more calls fit in the model's tokens-per-minute limit. The caller's rules are shorter, and Pipecat no longer adds its guidance for async tools to the caller's system prompt.
  - The caller answers the agent's opening turn more often. With the old rules, many of these replies had no words.
  - When a scenario tells the caller to end the call at a named point, the caller ends it there more often.
  - The caller follows its scenarios with new rules, so a scenario can give a different result than on 0.9.1.

## v0.9.1 (2026-10-28)

### Feat

- **caller**: STT TTFS per caller reply and Voice AI part names with tooltips (#27)
  - Each reply of the caller's model now also records its STT TTFS: the time from the end of the agent's speech to the last final STT transcript before the caller's LLM got the request. The `caller_reply_time` log line has it as `stt_ttfs_ms`, the **Caller** card on the **Metrics** tab shows its p50 and p90 under the parts, and the reply time on the transcript shows it on hover.
  - The STT TTFS overlaps the VAD endpointing, so it does not add up with the parts. For an STT that finalizes on its own endpointing, such as Deepgram, it shows if the STT is fast enough for a shorter `stop_secs`. Soniox sends its final transcript only when the VAD stops, so its STT TTFS always includes the `stop_secs`.
  - The parts now have their Voice AI names: VAD endpointing, STT after VAD stop, turn detection, LLM TTFT, sentence aggregation, TTS TTFB and output transport. Point to the name of a part, or move the focus to it, to see what it measures.
  - The **Caller** card always shows VAD endpointing, STT after VAD stop, turn detection, LLM TTFT and TTS TTFB, also at 0 ms.
  - The other fields of the `caller_reply_time` log line do not change. Calls from before this version have no STT TTFS.

## v0.9.0 (2026-10-28)

### Feat

- **caller**: run each phone call in its own process (#26)
  - A new start setting, `YAKSH_CALL_PROCESSES=true`, runs each phone call in a process of its own. Then the calls of one worker use all CPUs of the server. The default is off: all calls run in the worker process, as before.
  - In this mode, a call that stops or stalls fails alone, and the worker stays up. A call that never starts, for example when the dial fails, gives its process to the next call.
  - Each call needs more memory and CPU in this mode. At rest the worker uses about 660 MB, and each call adds about 100 MB. A call uses 1.5 to 2 times the CPU that it uses in one process. Raise **Phone calls at once** in steps, as the self-hosting guide tells.
  - Use Linux for many calls, and run the worker under an init process, as `docker/compose.yaml` does.
  - In process mode, the **worker stall** fault of a call counts the stalls of its own process and of the worker, which relays its audio.
  - In both modes, the turn model now uses one CPU thread. It uses about a tenth of the CPU for each call that it used before.

## v0.8.1 (2026-10-28)

### Feat

- **speech**: choose speech-to-text and text-to-speech providers in Settings (#25)
  - **Settings** has a **Speech to text** panel. One provider hears the agent on every call: Deepgram, Sarvam, AssemblyAI, Soniox or Gladia, with its model, key and address. Deepgram stays the default, so an install with a Deepgram key needs no change.
  - **Settings** has a **Text to speech** list. ElevenLabs, Cartesia, Sarvam, Azure and Nimble (Plivo's text-to-speech) can each have a key, and each voice uses one of them. Nimble has its own Auth ID and Auth token, and a base URL for the gateway of your region. The built-in personas keep their ElevenLabs voices.
  - **Test** on a provider checks its saved settings and shows the result next to the button. A speech-to-text key passes when the provider writes a transcript of a short English clip. A text-to-speech key passes when the provider speaks one word.
  - On the **Voices** page, ElevenLabs and Nimble fill in a voice's details from its ID. For the other providers, you enter the details, and Yaksh adds the voice only after the provider speaks a line in it. Each voice shows its provider.
  - A phone run does not start when the speech-to-text provider does not hear the language that the agent should answer in, or when a persona's voice provider has no key or does not speak the persona's language.
  - Sarvam gives no word timing. When the agent cuts off a Sarvam voice, the transcript is exact to a sentence, not to a word.
  - The **Metrics** tab and the `caller_reply_time` log line name the speech providers of the call.
  - The Plivo Auth ID and Auth token are now saved and removed only together.
  - Change the speech settings, and add voices of the new providers, only after every Yaksh process runs this version.

## v0.8.0 (2026-10-28)

### Feat

- show where each caller reply's time goes, in the logs, the Metrics tab and Settings (#24)
  - On a phone test, Yaksh now records how long its caller took to reply to the agent and where that time went: the silence wait, the transcript, the end-of-turn check, the LLM, the tools, the wait for a sentence, the speech synthesis and the output.
  - The worker writes one `caller_reply_time` log line for each reply, with the caller's models, the total and each part in ms, so a log store can give daily numbers per caller model and per part.
  - The **Metrics** tab of a conversation is now three cards: **Agent**, with a bar for each of its replies, then **Caller**, with the reply time and its parts, then **Call**.
  - On the transcript, each reply of the caller's model shows its reply time. Point to it to see its parts.
  - **Settings › Models** shows the caller's reply time for each model and effort over the phone calls of the last 7 days.
  - Response times under a second now show in ms, such as 820ms.
  - Only replies of the caller's model count: not its fixed lines, nudges or goodbyes, and not the lines of its voicemail or call screener. Calls from before this version have no caller reply time.

## v0.7.1 (2026-10-27)

### Feat

- **caller**: press keypad keys when the agent asks the caller to type (#19)
  - On a phone test, the caller now presses keys on its phone keypad (DTMF) when the agent asks it to type or enter something, such as a card number followed by the pound key. Before, the caller could only say the keys.
  - The caller presses the keys 0 to 9, * and #. A press goes to the agent as DTMF, not as tones in the caller's audio.
  - The transcript shows a press as a caller turn with a **DTMF** badge. The judges read it as keys pressed on the keypad, not spoken, and **What the agent heard** does not check it.
  - After a press, a quiet agent gets the same nudge as after the caller speaks.
  - A text test has no keypad, so its caller does not press keys.
- **cli**: add scenarios and agent rules from files, and rewrite the skill (#23)
  - `yaksh scenario create -f` and `yaksh scenario update -f` read a scenario from a YAML or JSON file. `yaksh scenario generate` lets a model write scenarios for an agent and prints each one that it saves. `yaksh agent update --rules-file` sets the agent rules from a file.
  - The skill, which `yaksh guide` also prints, is new. It tells a coding agent how to write scenarios and agent rules, run them, read the verdicts, and find whether the agent or the test caused each failure. The coding agent reports the evidence, and the user decides what to change in the voice agent. Before, the skill told the coding agent to change the voice agent after each failure.

## v0.7.0 (2026-10-27)

### Feat

- **console**: show the server's release in the sidebar (#22)
  - The sidebar footer shows the release the server runs, such as "Yaksh 0.7.0", linked to its release notes. An open console shows a new release within 5 minutes of a deploy.

## v0.6.0 (2026-10-27)

### Feat

- **evaluation**: give the judges the agent's own side of the call (#20)
  - For an agent with an agent record, the judges now read the agent's own words from it: what the agent said and what its speech-to-text heard, in order with its tool calls. A speech-to-text error in Yaksh's transcript of the agent no longer fails the agent, and a question the agent asks after it misheard the caller is judged by what it heard.
  - The **Agent record** tab shows a line that the agent said while a tool ran before the tool's result, in the same order as the judges read it.
  - The instruction and hallucination checks can quote a line of the agent record.
  - A caller turn that the agent spoke over is now marked **cut off**: part or none of it played. Before, it was marked **not played**.
  - **What the agent heard** no longer reports a name that the caller said, and did not spell, as heard differently when it sounds the same.
  - Calls judged before this version keep their verdicts. Run the scenario again to get new verdicts.

### Fix

- **caller**: let the phone caller stay silent while the agent works (#21)
  - On a phone test, the caller now says nothing when the agent only asks it to wait or says it is working, such as "let me check that". Before, it could say "Sure." a few seconds late, while the agent started its next line.
  - A caller reply with no words is no longer an error. Before, it made a finished call invalid, and Yaksh ran the call again.
  - On a text test, the caller still gives a short reply to such a turn, because a text agent answers only after the caller sends a message.

## v0.5.2 (2026-10-26)

### Fix

- **caller**: wait and ask the model again after a rate limit (#18)
  - When the LLM provider refuses a request of the caller's model for a rate limit, the caller waits 1, 2, 4 and 8 seconds and asks again, on phone and text tests. Before, one refusal made the whole conversation invalid, also when the call went on. A call that ends while the caller still waits stays invalid.
- **screener**: count answers after the question and judge calls by who they reached (#17)
  - Speech that ends before the screener's question ends no longer counts as the agent's answer. An agent that talks over the question now gets time to answer after it. Before, the screener took that speech as the answer and went on at once.
  - A screener call counts as a call where the caller talked only when the persona picked up. A call that ends at the screener, because the screener ended it or the agent hung up, now shows under **No caller talked**, and only the rules for the call screener judge it. Before, the persona's **After screening** setting decided this, also for a call that ended at the screener.
  - Screener calls judged before this version keep their verdicts. On the run page, the ones that ended at the screener move to **No caller talked**, and the run's numbers change with them. Run the scenario again to get new verdicts.
  - The run dialog now warns for every persona when no deciding rule checks the call screener. Before, it did not warn when the persona picks up.

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
