type Direction = "inbound" | "outbound";
type Transport = "phone";
export type ConversationStatus =
  | "queued"
  | "running"
  | "ending"
  | "completed"
  | "failed"
  | "invalid"
  | "cancelled";
type EndReason =
  | "user_request"
  | "caller_hangup"
  | "agent_hangup"
  | "agent_silent"
  | "no_answer"
  | "stream_ended"
  | "duration_limit"
  | "error"
  | "worker_stopped"
  | "lease_lost";

export const END_REASON_LABELS: Record<EndReason, string> = {
  user_request: "Stopped on request",
  caller_hangup: "Caller hung up",
  agent_hangup: "Agent hung up",
  agent_silent: "Agent stayed silent",
  no_answer: "No answer",
  stream_ended: "Stream ended",
  duration_limit: "Time limit reached",
  error: "Error",
  worker_stopped: "Worker stopped",
  lease_lost: "Worker lease lost",
};

export interface CallerClaim {
  success: boolean;
  reason: string;
}
type Role = "agent" | "caller";
export type Language = "en" | "hinglish";
export type VoiceGender = "male" | "female" | "neutral";
type Provenance = "transmitted" | "cut" | "unconfirmed";
type WireEventKind =
  | "connect_started"
  | "ringing"
  | "answered"
  | "connected"
  | "caller_audio_start"
  | "caller_audio_end"
  | "agent_audio"
  | "clear_audio"
  | "silence_greeting"
  | "stop"
  | "caller_error";

export const ACTIVE_STATUSES: ConversationStatus[] = ["queued", "running", "ending"];

export const LANGUAGE_NAMES: Record<Language, string> = {
  en: "English",
  hinglish: "Hinglish",
};

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Agent {
  id: string;
  name: string;
  external_id: string | null;
  direction: Direction;
  transport: Transport;
  agent_number: string;
  agent_speaks_first: boolean;
  brief: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
}

export interface AgentInput {
  name: string;
  external_id: string | null;
  direction: Direction;
  transport: Transport;
  agent_number: string;
  agent_speaks_first: boolean;
  brief: string | null;
}

export type VoiceProvider = "elevenlabs";

export interface VoiceSettings {
  provider: VoiceProvider;
  id: string;
  speed: number;
  stability: number;
}

export interface Voice {
  id: string;
  provider: VoiceProvider;
  provider_voice_id: string;
  name: string;
  gender: VoiceGender | null;
  accent: string | null;
  languages: Language[];
  listed_languages: Language[];
  builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderVoice {
  id: string;
  name: string;
  gender: VoiceGender | null;
  accent: string | null;
  listed_languages: Language[];
}

export interface VoiceInput {
  provider: VoiceProvider;
  provider_voice_id: string;
  name: string;
  languages: Language[];
}

export interface VoiceEdit {
  name: string;
  languages: Language[];
}

export interface PersonaInput {
  name: string;
  prompt: string;
  language: Language;
  voice: VoiceSettings;
}

export interface Persona {
  id: string;
  name: string;
  builtin_key: string | null;
  prompt: string;
  language: Language;
  voice: VoiceSettings;
  voice_gender: VoiceGender | null;
  current_version: number;
  created_at: string;
  updated_at: string;
}

export interface Fact {
  name: string;
  value: string;
}

export interface ScenarioConfig {
  goal: string;
  known_facts: Fact[];
  unknown_facts: string[];
  criteria: string[];
}

export interface ScenarioInput extends ScenarioConfig {
  name: string;
}

export interface Scenario extends ScenarioInput {
  id: string;
  agent_id: string;
  current_version: number;
  created_at: string;
  updated_at: string;
}

export interface Turn {
  role: Role;
  text: string;
  started_at_ms: number;
  ended_at_ms: number;
  provenance: Provenance | null;
  scripted: boolean;
}

export interface WireEvent {
  kind: WireEventKind;
  at_ms: number;
}

interface Validity {
  ok: boolean;
  reasons: string[];
}

export interface ConversationSummary {
  id: string;
  agent_id: string;
  agent_version_id: string;
  agent_version: number;
  agent_name: string;
  persona_id: string;
  persona_version_id: string;
  persona_version: number;
  persona_name: string;
  scenario_id: string;
  scenario_version_id: string;
  scenario_version: number;
  scenario_name: string;
  language: Language;
  channel: "voice";
  caller_number: string | null;
  call_uuid: string | null;
  max_duration_s: number;
  status: ConversationStatus;
  end_reason: EndReason | null;
  failure_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
  talk_ms: number | null;
  recording_url: string | null;
  created_at: string;
}

export interface Conversation extends ConversationSummary {
  instructions: string;
  scenario: ScenarioConfig;
  transcript: Turn[];
  wire_events: WireEvent[];
  validity: Validity | null;
  caller_claim: CallerClaim | null;
}

export interface ConversationInput {
  agent_id: string;
  persona_id: string;
  scenario_id: string;
  max_duration_s?: number;
}
