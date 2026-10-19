import {
  EMPTY_ENDPOINT,
  EMPTY_OUTBOUND,
  normalizeNumber,
  type OutboundDraft,
  toEndpoint,
  toOutbound,
  toOutboundDraft,
} from "@/lib/outbound";
import type {
  Agent,
  AgentInput,
  AgentLanguage,
  AgentSummary,
  Direction,
  Endpoint,
} from "@/lib/types";

/** The API's limits for the brief, which every agent has. */
export const MIN_BRIEF_CHARS = 20;

/** The brief's length as the API counts it: in characters, without NULs and outer spaces. */
export const briefLength = (brief: string) => [...brief.replaceAll("\0", "").trim()].length;
export const MAX_BRIEF_CHARS = 10_000;

export interface Draft {
  name: string;
  external_id: string;
  /** Null until the user chooses who starts the conversation. */
  direction: Direction | null;
  /** Yaksh reaches the agent by phone: its number, or its start request when it is outbound. */
  phone: boolean;
  /** Yaksh reaches the agent over text, at its endpoint. */
  text: boolean;
  agent_number: string;
  outbound: OutboundDraft;
  endpoint: Endpoint;
  agent_speaks_first: boolean;
  languages: AgentLanguage[];
  brief: string;
  config: string;
}

export const EMPTY_DRAFT: Draft = {
  name: "",
  external_id: "",
  direction: null,
  phone: true,
  text: false,
  agent_number: "",
  outbound: EMPTY_OUTBOUND,
  endpoint: EMPTY_ENDPOINT,
  agent_speaks_first: true,
  languages: ["en-US"],
  brief: "",
  config: "",
};

export function toDraft(agent: Agent): Draft {
  return {
    name: agent.name,
    external_id: agent.external_id ?? "",
    direction: agent.direction,
    phone: agent.transports.includes("phone"),
    text: agent.transports.includes("text"),
    agent_number: agent.agent_number ?? "",
    outbound: agent.outbound ? toOutboundDraft(agent.outbound) : EMPTY_OUTBOUND,
    endpoint: agent.endpoint ?? EMPTY_ENDPOINT,
    agent_speaks_first: agent.agent_speaks_first,
    languages: agent.languages,
    brief: agent.brief,
    config: agent.config ?? "",
  };
}

/** Whether the agent gets the data sets' agent data: an outbound agent in its start request, an
 * agent with a text endpoint in its first request. */
export const sendsAgentData = (agent: AgentSummary) =>
  agent.endpoint !== null || agent.direction === "outbound";

export const CONTEXT_NOTE =
  "Yaksh writes test scenarios from these, and the judges check calls against the config.";

/** The agent to send. Only a draft with no problems is sent, so it has a direction. */
export function toInput(draft: Draft): AgentInput {
  const { direction, phone, text } = draft;
  if (direction === null) throw new Error("Choose who starts the conversation.");
  const outbound = direction === "outbound";
  return {
    name: draft.name.trim(),
    external_id: draft.external_id.trim() || null,
    direction,
    agent_number: phone && !outbound ? normalizeNumber(draft.agent_number) : null,
    outbound: phone && outbound ? toOutbound(draft.outbound) : null,
    endpoint: text ? toEndpoint(draft.endpoint) : null,
    agent_speaks_first: draft.agent_speaks_first,
    languages: draft.languages,
    brief: draft.brief.trim(),
    config: draft.config.trim() ? draft.config : null,
  };
}
