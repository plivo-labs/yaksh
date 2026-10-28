import type {
  SecretName,
  SettingsProvider,
  SettingsValues,
  SttProvider,
  TtsModel,
  TtsTraits,
  VoiceProvider,
  VoiceSettings,
} from "@/lib/types";

type Section = keyof SettingsValues;

/** What a speech provider's panel shows and saves: its settings section, the field that holds
 * its address (its key goes only there), its key, and its Test. */
export interface SpeechProvider<P extends string> {
  value: P;
  label: string;
  section: Section;
  /** The section's address field; null when the provider's host is fixed. */
  address: "base_url" | "url" | null;
  secret: SecretName;
  test: SettingsProvider;
}

export const STT_PROVIDERS: SpeechProvider<SttProvider>[] = [
  {
    value: "deepgram",
    label: "Deepgram",
    section: "deepgram",
    address: "base_url",
    secret: "deepgram_api_key",
    test: "deepgram",
  },
  {
    value: "sarvam",
    label: "Sarvam",
    section: "sarvam_stt",
    address: null,
    secret: "sarvam_api_key",
    test: "sarvam_stt",
  },
  {
    value: "assemblyai",
    label: "AssemblyAI",
    section: "assemblyai",
    address: "url",
    secret: "assemblyai_api_key",
    test: "assemblyai",
  },
  {
    value: "soniox",
    label: "Soniox",
    section: "soniox",
    address: "url",
    secret: "soniox_api_key",
    test: "soniox",
  },
  {
    value: "gladia",
    label: "Gladia",
    section: "gladia",
    address: "url",
    secret: "gladia_api_key",
    test: "gladia",
  },
];

export const sttProvider = (value: SttProvider) =>
  STT_PROVIDERS.find((provider) => provider.value === value) ?? STT_PROVIDERS[0];

/** The languages each provider's streaming model hears; the server refuses a phone run whose
 * agent should answer in another. */
export const STT_LANGUAGES: Record<SttProvider, readonly string[]> = {
  deepgram: ["en", "hi", "bn", "gu", "kn", "mr", "ta", "te", "es"],
  sarvam: ["en", "hi", "bn", "gu", "kn", "mr", "ta", "te"],
  assemblyai: ["en", "hi", "mr", "es"],
  soniox: ["en", "hi", "bn", "gu", "kn", "mr", "ta", "te", "es"],
  gladia: ["en", "hi", "bn", "gu", "kn", "mr", "ta", "te", "es"],
};

/** A text-to-speech provider's settings and key. How its voices behave, and the models they
 * use, come from the server's list of providers (`useVoiceProviders`). */
export interface TtsProvider extends Omit<SpeechProvider<VoiceProvider>, "address" | "secret"> {
  /** Its key, or Nimble's Auth ID and Auth token, which are saved together. */
  secrets: readonly SecretName[];
  /** The section's address field; Azure's is its region. */
  address: "base_url" | "url" | "region";
}

export const TTS_PROVIDERS: TtsProvider[] = [
  {
    value: "elevenlabs",
    label: "ElevenLabs",
    section: "elevenlabs",
    address: "url",
    secrets: ["elevenlabs_api_key"],
    test: "elevenlabs",
  },
  {
    value: "cartesia",
    label: "Cartesia",
    section: "cartesia",
    address: "url",
    secrets: ["cartesia_api_key"],
    test: "cartesia",
  },
  {
    value: "sarvam",
    label: "Sarvam",
    section: "sarvam_tts",
    address: "base_url",
    secrets: ["sarvam_api_key"],
    test: "sarvam_tts",
  },
  {
    value: "azure",
    label: "Azure",
    section: "azure",
    address: "region",
    secrets: ["azure_api_key"],
    test: "azure",
  },
  {
    value: "nimble",
    label: "Nimble",
    section: "nimble",
    address: "base_url",
    secrets: ["nimble_auth_id", "nimble_auth_token"],
    test: "nimble",
  },
];

/** Whether every secret the provider needs is saved. */
export const hasCredential = (
  provider: TtsProvider,
  secrets: Partial<Record<SecretName, unknown>> | undefined,
) => provider.secrets.every((name) => Boolean(secrets?.[name]));

export const ttsProvider = (value: VoiceProvider) =>
  TTS_PROVIDERS.find((provider) => provider.value === value) ?? TTS_PROVIDERS[0];

/** The tag of a provider without word timestamps, and what it means for a call. */
export const CUTS_AT_SENTENCES = {
  label: "Cuts at sentences",
  tip: "If the agent talks over the caller, the transcript cuts the caller's line at a whole sentence, not at a word. This provider does not report when each word plays.",
};

export const ttsTraits = (providers: readonly TtsTraits[], value: VoiceProvider) =>
  providers.find((provider) => provider.provider === value) ?? providers[0];

/** A voice's model; undefined for a model that is not in the provider's list. */
export const ttsModel = (
  traits: TtsTraits,
  model: string | null | undefined,
): TtsModel | undefined => traits.models.find((item) => item.id === (model ?? null));

/** The speed range of a voice's model. A model that is not in the list takes the widest range
 * of the provider, as the server does. */
export function speedRange(traits: TtsTraits, model: string | null | undefined): [number, number] {
  const found = ttsModel(traits, model);
  if (found) return [found.speed_min, found.speed_max];
  return [
    Math.min(...traits.models.map((item) => item.speed_min)),
    Math.max(...traits.models.map((item) => item.speed_max)),
  ];
}

/** A voice's provider and model, such as "ElevenLabs Flash v2.5"; the provider alone when it
 * has no model choice. */
export function modelName(traits: TtsTraits, model: string | null | undefined): string {
  if (model == null) return traits.label;
  return `${traits.label} ${ttsModel(traits, model)?.label ?? model}`;
}

/** A voice at its natural pace, with ElevenLabs' default stability: how a voice that no persona
 * has set up speaks in a preview. */
export const defaultSettings = (
  provider: VoiceProvider,
  id: string,
  model: string | null,
): VoiceSettings => ({
  provider,
  id,
  model,
  speed: 1,
  stability: provider === "elevenlabs" ? 0.5 : null,
});
