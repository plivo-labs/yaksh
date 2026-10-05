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
  | "no_call"
  | "turn_limit";

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
  turn_limit: "Turn limit reached",
};

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

/** What each wire event means, from where Truman records it. */
export const WIRE_EVENT_HELP: Record<WireEventKind, string> = {
  connect_started: "Truman started the call: it dials the agent, or waits for the agent's call.",
  waiting_for_call: "Truman waits for the agent to call the number it leased for this test.",
  trigger_sent:
    "Truman tried to send the request that makes the agent call. The text below gives the result, or why it was not sent.",
  ringing: "Plivo reports that the agent's phone rings.",
  answered: "The call is answered: the agent picked up, or Truman took the agent's call.",
  connected: "The audio stream is open. Talk time and the recording start here.",
  caller_audio_start:
    "Truman started to send the caller's speech. This does not prove that the agent heard it.",
  caller_audio_end: "Truman stopped sending the caller's speech.",
  agent_audio:
    "Sound from the agent's side started after a quiet stretch: speech, music, a beep or line noise.",
  clear_audio:
    "The agent started to speak, so Truman told Plivo to drop caller speech still queued. It cuts the caller off only when the caller was still speaking.",
  silence_greeting: "The agent should speak first but stayed silent, so the caller said hello.",
  stop: "Plivo stopped the audio stream.",
  caller_error:
    "Plivo could not play the caller's audio or reported an error, or a speech or model service of the caller failed.",
};

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

export type NoiseSound =
  | "none"
  | "street"
  | "cafe"
  | "office"
  | "car"
  | "tv"
  | "crowd"
  | "kitchen"
  | "wind";
export type NoiseLevel = "light" | "busy" | "loud";

/** The sound behind the caller. With the sound "none", the level is always "busy". */
export interface BackgroundNoise {
  sound: NoiseSound;
  level: NoiseLevel;
}

export const NO_NOISE: BackgroundNoise = { sound: "none", level: "busy" };

export const NOISE_SOUND_ITEMS: { value: NoiseSound; label: string }[] = [
  { value: "none", label: "None" },
  { value: "street", label: "Street" },
  { value: "cafe", label: "Cafe" },
  { value: "office", label: "Office" },
  { value: "car", label: "Car" },
  { value: "tv", label: "TV" },
  { value: "crowd", label: "Crowd" },
  { value: "kitchen", label: "Kitchen" },
  { value: "wind", label: "Wind" },
];

export const NOISE_SOUND_LABELS = Object.fromEntries(
  NOISE_SOUND_ITEMS.map((item) => [item.value, item.label]),
) as Record<NoiseSound, string>;

export const NOISE_LEVEL_ITEMS: { value: NoiseLevel; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "busy", label: "Busy" },
  { value: "loud", label: "Loud" },
];

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
  rules: AgentRule[];
}

/** A check on every judged call of the agent, judged like a criterion. Its gate is decided in
 * code before any model call. */
export interface LlmRule {
  kind: "llm";
  key: string;
  name: string;
  gate: "always" | "agent_spoke";
  applies_when: string;
  pass_when: string;
  fail_when: string;
  not_a_failure: string | null;
  role: "deciding" | "reporting";
}

/** A phrase or pattern that code looks for in the agent's lines. */
export interface PhraseRule {
  kind: "phrase";
  key: string;
  name: string;
  expects: "required" | "forbidden";
  match: "phrase" | "regex";
  value: string;
  where: "first_agent_turn" | "any_agent_turn";
  role: "deciding" | "reporting";
}

export type AgentRule = LlmRule | PhraseRule;

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
  rules: AgentRule[];
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
  background_noise: BackgroundNoise;
}

export interface Persona {
  id: string;
  name: string;
  builtin_key: string | null;
  prompt: string;
  language: Language;
  voice: VoiceSettings;
  voice_gender: VoiceGender | null;
  background_noise: BackgroundNoise;
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
  /** On an agent turn that starts a reply: how long the agent made the caller wait. Turns that
   * arrive live during the call have neither field. */
  response_ms?: number | null;
  /** On an agent turn that starts a reply: the agent began before the caller finished. */
  talked_over?: boolean;
}

/** The agent's response times in one call; null on a call that was not measured. */
export interface LatencySummary {
  p50_ms: number | null;
  p90_ms: number | null;
  replies: number;
  talked_over: number;
}

/** One reply on the call's clock: when the caller's reply ended, and when the agent's speech
 * began. The speech comes first in a talk-over. */
export interface Reply {
  start_ms: number;
  speech_ms: number;
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
  max_turns: number;
  background_noise: BackgroundNoise;
  status: ConversationStatus;
  end_reason: EndReason | null;
  failure_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
  talk_ms: number | null;
  latency: LatencySummary | null;
  /** Null for a conversation with no evaluation: one not ended yet, or cancelled before its
   * call connected. */
  evaluation: EvaluationState | null;
  recording_url: string | null;
  /** Why the caller ended the call, in its own words: not a verdict. */
  caller_reason: string | null;
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
  replies: Reply[];
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
  /** How many agent turns the caller answers; the server default when null. */
  max_turns: number | null;
  /** Calls of the run on the line at once; null is no run limit. */
  max_parallel: number | null;
  /** The least time between two call starts; null is no wait. */
  start_interval_s: number | null;
  /** How many times a conversation that ends with an error is tried again; the server
   * default when null. */
  max_retries: number | null;
  /** Played in every conversation of the run; each persona's own setting when null. */
  background_noise: BackgroundNoise | null;
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
  max_turns: number;
  max_parallel: number | null;
  start_interval_s: number | null;
  max_retries: number;
  /** Each persona's own setting when null. */
  background_noise: BackgroundNoise | null;
  status: RunStatus;
  /** The latest attempt of each repeat of each scenario, by outcome group. */
  counts: Record<OutcomeGroup, number>;
  end_reasons: Partial<Record<EndReason, number>>;
  /** How many retries the run made. */
  retries: number;
  median_talk_ms: number | null;
  response_p50_ms: number | null;
  response_p90_ms: number | null;
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
  /** The server default when left out. */
  max_turns?: number;
  /** Another background for this one call; the persona's setting when left out. */
  background_noise?: BackgroundNoise;
}

export type GenerationMode = "agent" | "knowledge_base";
export type GenerationStatus = "running" | "done" | "failed" | "stopped";

export const MAX_GENERATED = 20;
/** Scenarios one bulk change takes. */
export const MAX_BULK = 500;

/** What the server uses for a field that a request leaves out. */
export interface Defaults {
  max_duration_s: number;
  max_turns: number;
  /** Of a run. */
  max_retries: number;
}

export interface GenerateInput {
  mode: GenerationMode;
  count: number;
  instructions: string;
  document_ids: string[];
  /** Spread over the new scenarios: a capability or question gets a persona again only after it got all of them. */
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

export type EvaluationState = "queued" | "running" | "done" | "failed";

/** The evaluation is still to come: queued, or running now. */
export function evaluationPending(state: EvaluationState | null): boolean {
  return state === "queued" || state === "running";
}

export interface Metric<T> {
  value: T;
  flags: string[];
}

export interface TurnTaking {
  expected: number;
  unanswered: number;
  talked_over: number;
  /** Waits of at least each length, by the length in ms. */
  at_least_ms: Record<string, number>;
  longest_wait_ms: number | null;
}

export interface Speaking {
  agent_ms: number;
  caller_ms: number;
  agent_share: number | null;
  longest_monologue_ms: number;
}

export interface AgentRepetition {
  runs: { text: string; count: number; at_ms: number }[];
}

/** The faults of a call saved in full, or, for a call whose worker stopped before that,
 * only that its record is incomplete. */
export type CaptureFaults =
  | {
      caller_error: string[];
      unconfirmed_caller_turns: number;
      media_gaps: number;
      media_gap_ms: number;
      worker_stall: { max_ms: number; at_ms: number } | null;
    }
  | { incomplete_record: true };

export interface Usage {
  settings: { llm_model: string; stt_model: string; tts_model: string } | null;
  usage: {
    llm_prompt_tokens: number | null;
    llm_completion_tokens: number | null;
    stt_audio_seconds: number | null;
    tts_characters: number | null;
  } | null;
  bill_duration_s: number | null;
  ringing_ms: number | null;
  answered_ms: number | null;
  stream_opened_ms: number | null;
}

export type Outcome =
  | "pass"
  | "fail"
  | "not_applicable"
  | "unsure"
  | "blocked"
  | "error"
  | "pending";
export type UnsureKind = "hidden_action" | "not_confirmed_played" | "unclear";
export type Verdict = "pass" | "fail" | "not_scored";

/** One judged criterion or agent rule. */
export interface EvaluationItem {
  item_key: string;
  /** The criterion's text or the rule's name. */
  subject: string;
  role: "deciding" | "reporting";
  decided_by: "code" | "jev" | "llm";
  machine_outcome: Outcome;
  unsure_kind: UnsureKind | null;
  effective_outcome: Outcome;
  effective_unsure_kind: UnsureKind | null;
  answer: Record<string, unknown> | null;
  error_reason: string | null;
  /** How Truman's caller affected this criterion, by the caller check. */
  caller_effect: { owner: string; effect: string; blame: string | null } | null;
  /** What Jev chose when it answered the item first; a Jev pass has no other answer. */
  jev_choice: string | null;
  jev_probabilities: Record<string, number> | null;
}

export interface ConversationEvaluation {
  evaluation: EvaluationState | null;
  /** Why the last attempt failed. */
  failure: string | null;
  /** By metric key; empty until the evaluation is done. A call gets only the metrics its
   * facts support. */
  metrics: Partial<{
    speech: Metric<Record<"agent" | "caller", { start_ms: number; end_ms: number }[]>>;
    response_time: Metric<Record<string, unknown>>;
    turn_taking: Metric<TurnTaking>;
    speaking: Metric<Speaking>;
    agent_repetition: Metric<AgentRepetition>;
    capture_faults: Metric<CaptureFaults>;
    usage: Metric<Usage>;
  }>;
  /** From the criteria; null when the call was not judged. */
  scenario_verdict: Verdict | null;
  conversation_verdict: Verdict | null;
  effective_scenario_verdict: Verdict | null;
  effective_conversation_verdict: Verdict | null;
  items: EvaluationItem[];
}

export const FLAG_TEXT: Record<string, string> = {
  unanswered: "Unanswered reply",
  long_wait: "Wait of 5s or more",
  dead_air: "Silence of 10s or more",
  media_gap: "Gap in the agent's media",
  monologue: "Monologue of 45s or more",
  repetition: "Repeated answer",
  caller_error: "Caller error",
  unconfirmed_caller_turns: "Unconfirmed caller turns",
  missing_recording: "No recording",
  no_agent_media: "No media from the agent",
  worker_stall: "Truman worker paused",
  incomplete_record: "Call record not saved in full",
};

/** How many of a total, with the 95% Wilson interval of the rate. */
export interface Share {
  count: number;
  total: number;
  low: number | null;
  high: number | null;
}

export interface RunNumbers {
  conversations: number;
  evaluated: number;
  pending: number;
  failed: number;
  connected: Share;
  errors_before_connect: number;
  response_p50_ms: number | null;
  response_p90_ms: number | null;
  /** Calls with a reply the agent did not answer, of the calls with turn taking. */
  unanswered: Share;
  /** Calls where the agent talked over a reply. */
  talked_over: Share;
  /** Calls with a wait of 5s or more. */
  long_wait: Share;
  /** Calls with a wait of 10s or more. */
  dead_air: Share;
  /** How many calls raised each flag. */
  flags: Record<string, number>;
}

export interface RunVerdicts {
  /** Calls whose evaluation is queued or running. */
  pending: number;
  /** Calls evaluated with no judge model: metrics, no verdict. */
  not_judged: number;
  /** The mean over scenarios of each one's passes over its scored calls. */
  pass_rate: number | null;
  /** Scored calls over judged calls; below 0.95 the worst-to-best range is the main number. */
  coverage: number | null;
  worst: number | null;
  best: number | null;
  interval_low: number | null;
  interval_high: number | null;
  pass_hat_2: number | null;
  pass_hat_2_scenarios: number;
  /** In the run's order. */
  scenarios: {
    scenario_id: string;
    name: string;
    category: Category;
    /** In repeat order; a null verdict means the evaluation failed. */
    calls: { conversation_id: string; repeat: number; verdict: Verdict | null }[];
    passes: number;
    scored: number;
  }[];
  inconsistent: string[];
  criteria: {
    scenario_id: string;
    number: number;
    text: string;
    counts: Record<string, number>;
    rate: number | null;
  }[];
  /** Criteria and agent rules by who decided them. */
  decided_by: Partial<Record<"code" | "jev" | "llm", number>>;
  /** Criteria and agent rules no judge could decide. */
  errors: number;
  callers: { persona: string; calls: number; likely: number; possible: number }[];
  judge_versions: { judge: string; model: string; version: string; items: number }[];
}

export interface RunMetrics {
  overall: RunNumbers;
  /** By the scenario's category as it is now; a category is not versioned. */
  by_category: { category: Category; numbers: RunNumbers }[];
  by_noise: { noise: BackgroundNoise; numbers: RunNumbers }[];
  verdicts: RunVerdicts;
}

export type LabelAnswer = "pass" | "fail" | "not_applicable" | "cannot_tell" | "blocked";
export type LabelReason =
  | "agent_error"
  | "applicability"
  | "transcript_error"
  | "spoken_form"
  | "date_or_time"
  | "read_back"
  | "window_or_order"
  | "exact_value"
  | "hidden_action"
  | "evidence_misread"
  | "criterion_ambiguous"
  | "caller_error"
  | "scenario_error"
  | "test_settings_error"
  | "line_or_audio"
  | "other";
export type Lane = "audit" | "ad_hoc";

export interface LabelRead {
  answer: LabelAnswer;
  /** Needed for a fail, can't tell or blocked. */
  reason: LabelReason | null;
  note: string | null;
  lane: Lane;
  /** Given before the labeler saw the machine result. */
  blind: boolean;
  created_at: string;
}

export interface ReviewItem {
  id: string;
  item_key: string;
  subject: string;
  role: "deciding" | "reporting";
  /** The machine result stays hidden until this labeler labels the item. */
  blind: boolean;
  machine: EvaluationItem | null;
  /** This labeler's latest label. */
  label: LabelRead | null;
}

export interface ReviewConversation {
  conversation: Conversation;
  lane: Lane;
  items: ReviewItem[];
  /** Null until this labeler has labeled every blind item. */
  verdicts: {
    scenario_verdict: Verdict | null;
    conversation_verdict: Verdict | null;
    effective_scenario_verdict: Verdict | null;
    effective_conversation_verdict: Verdict | null;
  } | null;
}

export interface QueuedReview {
  conversation_id: string;
  scenario_name: string;
  ended_at: string;
  items: number;
  labeled: number;
}

export interface JudgeAgreement {
  /** Each item counts once, by its first blind audit label. A judge version with no such label
   * is not listed: it is not yet measured. */
  versions: { judge: string; model: string; version: string; items: Share }[];
  /** Calls with a blind label on every criterion whose labels give the machine's verdict. */
  conversations: Share;
  /** Items with blind labels from two labelers where the two agree. */
  labelers: Share;
  /** Offered audit calls labeled in full. */
  offered_calls: Share;
}

export const OUTCOME_TEXT: Record<Outcome, string> = {
  pass: "Pass",
  fail: "Fail",
  not_applicable: "Not applicable",
  unsure: "Unsure",
  blocked: "Blocked",
  error: "Error",
  pending: "Labels disagree",
};

export const VERDICT_TEXT: Record<Verdict, string> = {
  pass: "Pass",
  fail: "Fail",
  not_scored: "Not scored",
};

export const DECIDED_BY_TEXT: Record<EvaluationItem["decided_by"], string> = {
  code: "Code",
  jev: "Jev",
  llm: "Judge model",
};

export const JUDGE_TEXT: Record<string, string> = {
  criterion: "Criterion",
  agent_rule: "Agent rule",
  instructions: "Instruction adherence",
  hallucination: "Hallucination",
  caller_check: "Caller check",
  jev: "Jev",
};

export const UNSURE_TEXT: Record<UnsureKind, string> = {
  hidden_action: "needs an action the call cannot show, so it counts as not applicable",
  not_confirmed_played: "the caller's audio is not confirmed as played",
  unclear: "the call does not show enough",
};

export const ERROR_TEXT: Record<string, string> = {
  judge_unavailable: "The judge model was not available.",
  judge_failed: "The judge model refused, rejected the request or stopped before its answer ended.",
  invalid_evidence: "The judge's quotes did not match the call, twice.",
  sources_too_large: "The config or the documents are too large for one request.",
  pattern_timeout: "The pattern ran past its time limit.",
};

/** Answers that name a problem, so they say which one. */
export const NEEDS_REASON: LabelAnswer[] = ["fail", "cannot_tell", "blocked"];

export const LABEL_ANSWERS: { value: LabelAnswer; label: string }[] = [
  { value: "pass", label: "Pass" },
  { value: "fail", label: "Fail" },
  { value: "not_applicable", label: "Not applicable" },
  { value: "cannot_tell", label: "Can't tell" },
  { value: "blocked", label: "Blocked" },
];

export const LABEL_REASONS: { value: LabelReason; label: string; example: string }[] = [
  {
    value: "agent_error",
    label: "Agent error",
    example: "The agent quoted $80; the criterion says $95.",
  },
  {
    value: "applicability",
    label: "Applicability",
    example: "The judge said not applicable, but the caller asked about the price.",
  },
  {
    value: "transcript_error",
    label: "Transcript error",
    example: 'The text says "eighty"; the recording says "ninety-five".',
  },
  {
    value: "spoken_form",
    label: "Spoken form",
    example: 'The agent said "two thirty p.m."; the judge wanted "2:30 PM".',
  },
  {
    value: "date_or_time",
    label: "Date or time",
    example: '"Next Tuesday" is a different day from the one the judge took.',
  },
  {
    value: "read_back",
    label: "Read-back",
    example: "The agent read back the time but not the date.",
  },
  {
    value: "window_or_order",
    label: "Window or order",
    example: "The agent asked for the date of birth after it booked.",
  },
  {
    value: "exact_value",
    label: "Exact value",
    example: '"Ninety-five" without "dollars", which the criterion allows.',
  },
  {
    value: "hidden_action",
    label: "Hidden action",
    example: "Only the clinic's calendar can show this.",
  },
  {
    value: "evidence_misread",
    label: "Evidence misread",
    example: "The judge quoted the caller's words as the agent's.",
  },
  {
    value: "criterion_ambiguous",
    label: "Criterion ambiguous",
    example: '"Confirms the booking" can mean a read-back or a question.',
  },
  {
    value: "caller_error",
    label: "Caller error",
    example: "The caller gave the wrong date of birth.",
  },
  {
    value: "scenario_error",
    label: "Scenario error",
    example: "The scenario asks for a Sunday slot; the clinic is closed on Sunday.",
  },
  {
    value: "test_settings_error",
    label: "Test settings error",
    example: "The turn limit ended the call before the booking.",
  },
  { value: "line_or_audio", label: "Line or audio", example: "The agent's audio dropped for 3s." },
  { value: "other", label: "Other", example: "Needs a note." },
];
