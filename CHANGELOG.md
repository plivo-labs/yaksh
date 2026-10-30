## v0.10.3 (2026-10-30)

### Fix

- **records**: keep Plivo CX record reads within its rate limit when many calls end together (#39)
  - Calls that end together no longer lose the agent's record of the call. Before, many calls to one Plivo CX agent sent more record requests than Plivo CX allows for one Auth ID (60 a minute), and some calls were judged without their record.
  - Yaksh now reads each run of the agent once for all the calls that ended together, and it asks for a run again only when its log has settled.
  - The requests of one Auth ID go at most about 50 a minute from one evaluator process. When Plivo CX asks Yaksh to wait, Yaksh waits that long before the next request.

## v0.10.2 (2026-10-29)

### Feat

- **scenarios**: allow instructions of up to 16,000 characters (#38)
- **cli**: pick the personas of a run with --persona (#37)

## v0.10.1 (2026-10-29)

### Feat

- **console**: edit interruptions and show where each line played (#36)
  - The scenario dialog has an Interruptions section. Add up to 3 lines there, each with its start (a phrase of the agent, or the start of an answer), its wait, the first answer that can start it, and the words of the caller. Errors show under their fields, as the API checks them.
  - The scenario page and the Scenario tab of a conversation list the lines. On a text run, or a call on which no caller talked, the tab says why no line played.
  - In the transcript, the turn of a line has the badge "Interruption N", and a note under it tells how far into which agent turn the caller spoke.

## v0.10.0 (2026-10-29)

### Feat

- let the caller interrupt the agent with fixed lines (#30)
  - A scenario can hold up to 3 interruptions: fixed lines that Yaksh's caller says while the agent still speaks, on phone calls. A line plays a set time into an answer of the agent, or when the agent says a phrase. Use them to test if the agent stops when a caller talks over it, and what it says next.
  - The agent cannot cut a line. When the agent stops for a line, the caller waits for its answer, and continues the call after 3 s of silence. When the agent talks over the line, the caller replies as usual.
  - The judges see where each line came, and they judge the call as any other call. Nothing measures yet how fast the agent stopped: write a criterion for what the agent must do after the line.
  - Write interruptions in the scenario file of the CLI or with the API. The console does not show them yet, and its Events card shows each try of a line. The docs have a new Interruptions page.
  - Add interruptions to a scenario only after every Yaksh process runs this version. An older process refuses a scenario that has them.

## v0.9.7 (2026-10-28)

### Fix

- **caller**: count a turn toward the turn limit only when its answer plays (#35)
  - The caller's turn limit now counts only the agent turns that the caller answered aloud. When the agent paused inside its own turn, for example between two sentences or during a tool call, the caller was asked for an answer that the agent's next words cut before it played. That pause used up a turn, so calls often ended at the turn limit before their scenarios were done.
  - The idle nudge, and a reply that only presses keys, do not count as answers. Calls can be longer than on 0.9.6, up to the turn limit or the call length limit.

## v0.9.6 (2026-10-28)

### Fix

- **caller**: ask the text caller again when its reply has no words (#34)
  - A text test no longer fails when the caller's model replies with no words. Before, such a reply stopped the conversation with the error "the caller's model answered with no words and no tool call".
  - When the agent's turn asks the caller nothing, the caller now writes a few words, such as "Okay". If a reply still has no words, Yaksh asks the model once more. A second reply with no words fails as before.
  - Phone calls do not change.

## v0.9.5 (2026-10-28)

### Feat

- **caller**: set the VAD stop and the turn detection wait in Settings (#33)
  - **Settings** has two new fields in the **Caller** panel. **VAD stop** is the silence after the agent's speech before turn detection runs, 0.1 to 2 seconds. **Turn detection max wait** is the most silence that the caller waits for when turn detection decides that the agent did not finish, 0.5 to 4 seconds.
  - The defaults are shorter than the old fixed values: a VAD stop of 0.3 seconds, not 0.6, and a max wait of 2 seconds, not 3. The caller now replies about 300 ms sooner after the agent stops speaking. With the shorter VAD stop, the caller's model sometimes runs a second time for a reply, when the agent's final transcript comes after the turn ended.
  - Each call records the two values that it used, and the `caller_reply_time` log line shows them. The agent's response time is still measured with a fixed VAD stop of 0.6 seconds, so it stays comparable with earlier calls.

## v0.9.4 (2026-10-28)

### Fix

- **caller**: stop a reply with no words from silencing the next turns (#32)
  - When the caller's reasoning model gives a reply with no words where it had to speak, the caller now answers the agent's next turn, such as "Are you still there?". Before, it often stayed silent through two or three of the agent's reminders, until the agent hung up.
  - A reply with no words leaves none of the model's reasoning in the conversation that the model sees on later turns. Nothing changes for a model without reasoning.
  - After the caller rightly stays silent while the agent works, it can miss the agent's next "Are you still there?" a little more often; the agent then asks again.

## v0.9.3 (2026-10-28)

### Feat

- **voices**: give each voice its own text-to-speech model, and search providers' voices (#29)
  - Each voice now has its own text-to-speech model. You can add the same provider voice once for each model, for example an ElevenLabs voice in Flash v2.5 and in v3. **Settings** no longer has a text-to-speech model; each provider panel keeps its key and address.
  - Each provider has a fixed list of models: ElevenLabs Flash v2.5, Multilingual v2, v4 Turbo, v4, v3 and v3 Conversational; Cartesia Sonic 3.6, 3.5 and 3; Sarvam Bulbul v4 Flash and Bulbul v3. Azure and Nimble have one model each. The **Add voice** dialog offers only the models that the saved key's account can use.
  - ElevenLabs v3 and v4 take the persona's language as a setting, also for Bengali, Gujarati, Kannada, Marathi and Telugu. Flash and Multilingual read these languages from the text. The v3 and v4 models have no speed setting, so their voices speak at speed 1.
  - The **Add voice** dialog searches the provider's own voices: the voices of your ElevenLabs and Cartesia accounts, the Azure voices of your region, Nimble's voices, and Sarvam's speakers of the chosen model. Select one or more voices and add them together. The dialog shows the result of each voice. You can still add a voice by its ID. To use a voice from ElevenLabs' public library, first add it to your ElevenLabs account.
  - The **Voices** page shows the model of each voice, and the persona editor keeps the speed in the model's range. Tooltips explain the models and **Cuts at sentences**, the tag of a provider without word timing.
  - The upgrade gives each saved voice and persona the model that its provider had in **Settings**.
  - Add voices, change persona voices or change the speech settings only after every Yaksh process runs this version. A Settings document exported from an earlier version still imports, and Yaksh ignores its text-to-speech models.

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
