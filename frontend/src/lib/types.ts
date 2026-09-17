export type Direction = "inbound" | "outbound";
export type Transport = "phone";
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
  | "goal_reached"
  | "goal_abandoned"
  | "agent_hangup"
  | "agent_silent"
  | "no_answer"
  | "duration_limit"
  | "error"
  | "process_restart";
export type Role = "agent" | "caller";
export type Provenance = "transmitted" | "cut";
export type WireEventKind =
  | "connect_started"
  | "ringing"
  | "answered"
  | "connected"
  | "caller_speech_start"
  | "caller_speech_end"
  | "agent_audio"
  | "checkpoint"
  | "clear_audio"
  | "stop"
  | "caller_error";

export const ACTIVE_STATUSES: ConversationStatus[] = ["queued", "running", "ending"];

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
  outbound_numbers: string[];
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

export interface Turn {
  role: Role;
  text: string;
  started_at_ms: number;
  ended_at_ms: number;
  provenance: Provenance | null;
}

export interface WireEvent {
  kind: WireEventKind;
  at_ms: number;
}

export interface Validity {
  ok: boolean;
  reasons: string[];
}

export interface ConversationSummary {
  id: string;
  agent_id: string;
  agent_version_id: string;
  agent_version: number;
  agent_name: string;
  channel: "voice";
  persona_prompt: string;
  caller_number: string | null;
  call_uuid: string | null;
  max_duration_s: number;
  status: ConversationStatus;
  end_reason: EndReason | null;
  failure_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  recording_url: string | null;
  created_at: string;
}

export interface Conversation extends ConversationSummary {
  transcript: Turn[];
  wire_events: WireEvent[];
  validity: Validity | null;
}

export interface ConversationInput {
  agent_id: string;
  persona_prompt: string;
  max_duration_s?: number;
}
