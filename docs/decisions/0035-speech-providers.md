# 0035 Speech providers are chosen on the Settings page and run through Pipecat

Date: 2026-10-27
Status: accepted. Changes 0005 (voices of any text-to-speech provider) and 0027 (more keys and addresses).

## Context

- Yaksh heard the agent only with Deepgram and spoke only with ElevenLabs. A team that tests agents in Indian languages, or that has a contract with another provider, could not use its own provider.
- Pipecat already runs many speech providers. Yaksh's call pipeline is a Pipecat pipeline.

## Decision

- **Speech to text.** One provider hears the agent on every call: Deepgram, Sarvam, AssemblyAI, Soniox or Gladia. Each has its own model and key, and an address where the provider has one. Deepgram stays the default, so an install that has a Deepgram key needs no change.
- **Text to speech.** Each voice belongs to one provider: ElevenLabs, Cartesia, Sarvam, Azure or Nimble. Several providers can have keys at the same time. A persona's voice keeps its provider.
- **Languages.** Each speech-to-text provider has a fixed list of the languages it hears, from its documentation. A phone run is refused when the provider in use does not hear the language the agent should answer in. Pipecat's language maps are not used for this check, because they accept codes that a provider does not support.
- **Turns.** Pipecat's turn settings stay at their defaults. Yaksh's voice detector and turn model decide when the agent's turn ends, with every provider.
- **Sentence timing.** A text-to-speech provider without word timestamps (Sarvam) is allowed. When the agent cuts off the caller, the transcript is then exact to a sentence, not to a word. The console says so where the provider or its voices show. Yaksh uses Sarvam's HTTP service, which sends each sentence's text after its audio; the transcript stamps each sentence at the end of its own audio.
- **One path for speech.** Calls, voice previews, the persona's own voicemail greeting and the key checks all use the same Pipecat service of the voice's provider. Speech outside a call ends only after the reply stops. An error, a stall or a dropped socket fails it, so a cut-short preview or greeting never passes.
- **Key checks.** A speech-to-text key is checked when a short English clip gives a transcript with words. A text-to-speech key is checked when a voice that every account of the provider has speaks one word. Sarvam has one key for both, and both checks run.
- **Addresses.** Each provider's key is bound to its address field, as in 0027: a URL, or Azure's region. The address is compared again when the key is saved, so a key is never saved next to an address that changed while it was checked.
- **Voices.** A provider with voice lookup (ElevenLabs, Nimble) fills a voice's details from its ID. For the other providers, the details are entered by hand, and Yaksh saves the voice only after the provider speaks a line in it.
- **Nimble.** Nimble has its own Auth ID and Auth token, bound to a base URL that the user sets for their region. As with Plivo, a change saves both or removes both, so a check never pairs a new half with an old half. A Nimble error before any audio of a reply is tried once more; any later error ends the call, because a replay would repeat words that the agent heard. Nimble never falls back to another provider's voice.
- **Deploys.** Old processes do not know the new providers. Change the speech settings, and add voices of new providers, only after every process runs this release.

## Why

- One provider for hearing keeps the agent's transcript comparable across calls. Voices are per persona, so several voice providers are useful at once.
- A test tool must not change a persona's voice by itself. That is why there is no fallback voice.
- One speech path means a preview sounds as the call will, and a key check proves what a call needs.

## Other options

- Every Pipecat provider. Rejected for now: each provider needs its own language list, sample-rate handling, key check and a real call before Yaksh can trust it.
- OpenAI text to speech. Rejected: its speech model is deprecated, and its replacement works only on the Realtime API.
- Sarvam's realtime speech-to-text endpoint. Not now: it needs beta access. Yaksh uses Sarvam's streaming endpoint.
