import type { SecretName, SettingsProvider, SettingsValues, SttProvider } from "@/lib/types";

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
