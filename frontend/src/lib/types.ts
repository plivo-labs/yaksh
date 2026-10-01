export type Direction = "inbound" | "outbound";
type Transport = "phone";
export type ConversationStatus =
  | "queued"
  | "running"
  | "ending"
  | "completed"
  | "failed"
  | "invalid"
  | "cancelled";
export type EndReason =
  | "user_request"
  | "caller_hangup"
  | "agent_hangup"
  | "agent_silent"
  | "no_answer"
  | "stream_ended"
  | "duration_limit"
  | "error"
  | "worker_stopped"
  | "lease_lost"
  | "trigger_failed"
  | "no_call";

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
  trigger_failed: "Trigger failed",
  no_call: "Agent did not call",
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
  | "caller_error"
  | "trigger_sent"
  | "waiting_for_call";

export const ACTIVE_STATUSES: ConversationStatus[] = ["queued", "running", "ending"];

/** How a conversation went, from its status and end reason only: what happened, not who is at
 * fault. */
export type OutcomeGroup =
  | "waiting"
  | "in_progress"
  | "completed"
  | "did_not_connect"
  | "error"
  | "cancelled";

export const OUTCOME_GROUPS: { value: OutcomeGroup; label: string }[] = [
  { value: "waiting", label: "Waiting" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "did_not_connect", label: "Did not connect" },
  { value: "error", label: "Error" },
  { value: "cancelled", label: "Cancelled" },
];

export type RunStatus = "queued" | "running" | "cancelling" | "done" | "cancelled";

export const ACTIVE_RUN_STATUSES: RunStatus[] = ["queued", "running", "cancelling"];

export type WaitingReason = "max_parallel" | "start_interval" | "worker_or_number";

export const WAITING_REASON_TEXT: Record<WaitingReason, string> = {
  max_parallel: "max parallel reached",
  start_interval: "delay between calls",
  worker_or_number: "a free worker or number",
};

export const LANGUAGE_NAMES: Record<Language, string> = {
  en: "English",
  hinglish: "Hinglish",
};

export const LANGUAGE_ITEMS = (Object.keys(LANGUAGE_NAMES) as Language[]).map((language) => ({
  value: language,
  label: LANGUAGE_NAMES[language],
}));

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Header {
  name: string;
  value: string;
}

export interface Trigger {
  url: string;
  headers: Header[];
  body: Record<string, unknown>;
}

export interface OutboundSettings {
  trigger: Trigger;
  calling_numbers: string[];
  dial_window_s: number;
}

export interface AgentSummary {
  id: string;
  name: string;
  external_id: string | null;
  direction: Direction;
  transport: Transport;
  agent_number: string | null;
  outbound: OutboundSettings | null;
  agent_speaks_first: boolean;
  language: Language;
  brief: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseEntry {
  document_id: string;
  name: string;
}

export interface KnowledgeBaseDocument extends KnowledgeBaseEntry {
  /** Null for pasted text, which has no file. */
  media_type: string | null;
  size_bytes: number | null;
  characters: number;
  pages: number | null;
  /** PDF pages with no text, such as scanned pages. */
  empty_pages: number | null;
}

export interface Agent extends AgentSummary {
  config: string | null;
  knowledge_base: KnowledgeBaseDocument[];
}

export interface DocumentSummary {
  id: string;
  name: string;
  media_type: string | null;
  size_bytes: number | null;
  characters: number;
  pages: number | null;
  empty_pages: number | null;
  created_at: string;
}

export interface DocumentRead extends DocumentSummary {
  text: string;
}

export interface AgentInput {
  name: string;
  external_id: string | null;
  direction: Direction;
  transport: Transport;
  agent_number: string | null;
  outbound: OutboundSettings | null;
  agent_speaks_first: boolean;
  language: Language;
  brief: string | null;
  config: string | null;
  /** Sent only when the agent is added; later changes go through the knowledge base panel. */
  knowledge_base?: KnowledgeBaseEntry[];
}

export interface PhoneNumber {
  number: string;
  alias: string | null;
  region: string | null;
  application_id: string | null;
  application_name: string | null;
  on_outbound_application: boolean;
  state: "in_use" | "resting" | "free";
}

export interface PhoneNumbers {
  items: PhoneNumber[];
  outbound_problem: string | null;
  /** How long a released number rests before an outbound test may use it. */
  rest_s: number;
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
  agent_data: Fact[];
}

export type Category = "happy_path" | "recovery" | "boundary";

export const CATEGORY_ITEMS: { value: Category; label: string; hint: string }[] = [
  { value: "happy_path", label: "Happy path", hint: "A normal request with correct information" },
  {
    value: "recovery",
    label: "Recovery",
    hint: "The caller gives wrong, partial, spelled-out or corrected information",
  },
  { value: "boundary", label: "Boundary", hint: "Out of scope, a refusal or a hand-off" },
];

export const CATEGORY_LABELS = Object.fromEntries(
  CATEGORY_ITEMS.map((item) => [item.value, item.label]),
) as Record<Category, string>;

export interface ScenarioInput extends ScenarioConfig {
  name: string;
  category: Category;
  /** Why the scenario exists. The caller and the judge never see it. */
  description: string | null;
  /** The persona the scenario runs with. */
  persona_id: string;
}

export interface Scenario extends ScenarioInput {
  id: string;
  agent_id: string;
  /** The generation that wrote it; null when written by hand. */
  generation_id: string | null;
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
  detail: string | null;
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
  agent_caller_id: string | null;
  direction: Direction;
  call_uuid: string | null;
  max_duration_s: number;
  status: ConversationStatus;
  end_reason: EndReason | null;
  failure_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
  talk_ms: number | null;
  recording_url: string | null;
  /** What the caller said when it hung up: a claim, not a verdict. */
  caller_claim: CallerClaim | null;
  run_id: string | null;
  repeat: number | null;
  attempt: number;
  /** The conversation this one tries again. */
  retry_of: string | null;
  created_at: string;
}

export interface Conversation extends ConversationSummary {
  instructions: string;
  scenario: ScenarioConfig;
  transcript: Turn[];
  wire_events: WireEvent[];
  validity: Validity | null;
  /** The retry that replaced this conversation. */
  retried_as: string | null;
}

export interface RunInput {
  agent_id: string;
  /** In the order the conversations of each repeat start. */
  scenario_ids: string[];
  repeats: number;
  /** The server default when null. */
  max_duration_s: number | null;
  /** Calls of the run on the line at once; null is no run limit. */
  max_parallel: number | null;
  /** The least time between two call starts; null is no wait. */
  start_interval_s: number | null;
  /** How many times a conversation that ends with an error is tried again; the server
   * default when null. */
  max_retries: number | null;
  name: string | null;
}

export interface RunSummary {
  id: string;
  agent_id: string;
  agent_version_id: string;
  agent_version: number;
  agent_name: string;
  name: string | null;
  repeats: number;
  max_duration_s: number;
  max_parallel: number | null;
  start_interval_s: number | null;
  max_retries: number;
  status: RunStatus;
  /** The latest attempt of each repeat of each scenario, by outcome group. */
  counts: Record<OutcomeGroup, number>;
  end_reasons: Partial<Record<EndReason, number>>;
  /** How many retries the run made. */
  retries: number;
  /** What the callers said when they hung up: claims, not verdicts. */
  caller_claims: { reached: number; not_reached: number };
  median_talk_ms: number | null;
  waiting_reason: WaitingReason | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  cancelled_at: string | null;
}

export interface Run extends RunSummary {
  scenario_ids: string[];
}

export interface ConversationInput {
  agent_id: string;
  scenario_id: string;
  /** Another persona for this one call; the scenario's own persona when left out. */
  persona_id?: string;
  /** The server default when left out. */
  max_duration_s?: number;
}

export type GenerationMode = "agent" | "knowledge_base";
export type GenerationStatus = "running" | "done" | "failed" | "stopped";

export const MAX_GENERATED = 20;
/** Scenarios one bulk change takes. */
export const MAX_BULK = 500;

export interface GenerateInput {
  mode: GenerationMode;
  count: number;
  instructions: string;
  document_ids: string[];
  /** Spread over the new scenarios, so each capability or question meets every persona. */
  persona_ids: string[];
}

export interface Generation {
  id: string;
  mode: GenerationMode;
  status: GenerationStatus;
  created_at: string;
  /** Its scenarios that are not deleted. */
  scenarios: number;
}
