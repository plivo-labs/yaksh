# 0039 A text-to-speech model belongs to each voice

Date: 2026-10-28
Status: accepted. Changes 0037 (one model for each provider, in Settings).

## Context

- Each text-to-speech provider had one model in Settings, and every voice of the provider used it.
- The models of one provider differ. Sarvam's bulbul:v3 and bulbul:v4-flash share no speaker, so a change of the Settings model broke every saved Sarvam voice. ElevenLabs' v3 and v4 take a language setting for Bengali, Gujarati, Kannada, Marathi and Telugu; Flash reads them from the text.
- A person had to find a voice's ID on the provider's site before adding it.
- Accounts differ in their models: on a real key, ElevenLabs' model list had no eleven_v4, eleven_v4_turbo or eleven_v3_conversational, and those models sent no audio.

## Decision

- A voice is a provider voice in one model. The same provider voice can be listed once for each model. Each provider has a fixed list of models, each with its speed range and languages, and a new voice gets the first. Settings holds no text-to-speech model.
- The model is stored in columns (`voices.model`, `personas.voice_model`, `persona_versions.voice_model`), never in a stored voice's JSON. An older process refuses a field that it does not know, and every process must keep reading the rows during a rolling deploy, because an install can go from any version to a newer one in one step.
- ElevenLabs' v3 and v4 work only on its dialogue socket, through Pipecat's ElevenLabsDialogueTTSService, which takes no speed. Yaksh flushes each sentence: the socket holds text until about 40 characters, and Pipecat ends an audio context that stays quiet for 3 s.
- The Voices page searches the provider's own voices and adds one or more at a time. It offers only the models that the account has: for ElevenLabs, from the key's own model list. A voice is added only after the provider speaks a line in it with its model.
- ElevenLabs' public library is not searched: a library voice speaks only after it is added to the account, as a real key showed.
- Speech to text keeps one provider and one model for the install.

## Consequences

- Migration 0007 gives each voice and persona the model that its provider had in Settings. A stored model outside the list becomes the first.
- The three old model settings stay in the stored row for one release, unread: a process of the previous release keeps its model there during the deploy. A later release removes them.
- Before a persona's voice changes, each of its versions without a model gets the model it speaks with now, so a queued call speaks as before.
- A persona version that an older process writes during a rollout has no model. Its voice keeps the persona's model.
- Change no voice, persona voice or Settings until every process runs this version.

## Rejected

- A default model in Settings for each provider: a second place for the same choice.
- A preparatory release that teaches older processes the new field: it would break the one-step upgrade.
- Sarvam's bulbul:v3 speakers from Pipecat's list: it disagrees with Sarvam's API reference.
