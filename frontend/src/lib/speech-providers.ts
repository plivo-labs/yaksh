import type {
  Language,
  SecretName,
  SettingsProvider,
  SettingsValues,
  SttProvider,
  VoiceProvider,
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

/** A text-to-speech provider: its settings and key, and how its voices behave. */
export interface TtsProvider extends Omit<SpeechProvider<VoiceProvider>, "address"> {
  /** The section's address field; Azure's is its region. */
  address: "base_url" | "url" | "region";
  /** False: the provider times whole sentences, so a cut-off reply is cut at a sentence. */
  wordTimestamps: boolean;
  /** The range of its speed or pace; 1 is the voice's natural pace. */
  speed: readonly [number, number];
  /** It describes a voice by its ID; otherwise the details are entered by hand. */
  lookup: boolean;
}

export const TTS_PROVIDERS: TtsProvider[] = [
  {
    value: "elevenlabs",
    label: "ElevenLabs",
    section: "elevenlabs",
    address: "url",
    secret: "elevenlabs_api_key",
    test: "elevenlabs",
    wordTimestamps: true,
    speed: [0.7, 1.2],
    lookup: true,
  },
  {
    value: "cartesia",
    label: "Cartesia",
    section: "cartesia",
    address: "url",
    secret: "cartesia_api_key",
    test: "cartesia",
    wordTimestamps: true,
    speed: [0.6, 1.5],
    lookup: false,
  },
  {
    value: "sarvam",
    label: "Sarvam",
    section: "sarvam_tts",
    address: "base_url",
    secret: "sarvam_api_key",
    test: "sarvam_tts",
    wordTimestamps: false,
    speed: [0.5, 2],
    lookup: false,
  },
  {
    value: "azure",
    label: "Azure",
    section: "azure",
    address: "region",
    secret: "azure_api_key",
    test: "azure",
    wordTimestamps: true,
    speed: [0.5, 2],
    lookup: false,
  },
];

export const ttsProvider = (value: VoiceProvider) =>
  TTS_PROVIDERS.find((provider) => provider.value === value) ?? TTS_PROVIDERS[0];

/** The languages each provider cannot speak; the console leaves them out for its voices. */
export const TTS_UNSPOKEN: Partial<Record<VoiceProvider, readonly Language[]>> = {
  sarvam: ["es"],
};
