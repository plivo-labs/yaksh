import {
  EMPTY_OUTBOUND,
  normalizeNumber,
  type OutboundDraft,
  toOutbound,
  toOutboundDraft,
} from "@/lib/outbound";
import type { Agent, AgentInput, AgentLanguage, Direction } from "@/lib/types";

/** The API's limits for the brief, which every agent has. */
export const MIN_BRIEF_CHARS = 20;

/** The brief's length as the API counts it: in characters, without NULs and outer spaces. */
export const briefLength = (brief: string) => [...brief.replaceAll("\0", "").trim()].length;
export const MAX_BRIEF_CHARS = 10_000;

export interface Draft {
  name: string;
  external_id: string;
  /** Null until the user chooses how Yaksh reaches a new agent. */
  direction: Direction | null;
  agent_number: string;
  outbound: OutboundDraft;
  agent_speaks_first: boolean;
  languages: AgentLanguage[];
  brief: string;
  config: string;
}

export const EMPTY_DRAFT: Draft = {
  name: "",
  external_id: "",
  direction: null,
  agent_number: "",
  outbound: EMPTY_OUTBOUND,
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
    agent_number: agent.agent_number ?? "",
    outbound: agent.outbound ? toOutboundDraft(agent.outbound) : EMPTY_OUTBOUND,
    agent_speaks_first: agent.agent_speaks_first,
    languages: agent.languages,
    brief: agent.brief,
    config: agent.config ?? "",
  };
}

export const CONTEXT_NOTE =
  "Yaksh writes test scenarios from these, and the judges check calls against the config.";

/** The agent to send. Only a draft with no problems is sent, so it has a direction. */
export function toInput(draft: Draft): AgentInput {
  const { direction } = draft;
  if (direction === null) throw new Error("Choose how Yaksh reaches the agent.");
  const outbound = direction === "outbound";
  return {
    name: draft.name.trim(),
    external_id: draft.external_id.trim() || null,
    direction,
    transport: "phone",
    agent_number: outbound ? null : normalizeNumber(draft.agent_number),
    outbound: outbound ? toOutbound(draft.outbound) : null,
    agent_speaks_first: draft.agent_speaks_first,
    languages: draft.languages,
    brief: draft.brief.trim(),
    config: draft.config.trim() ? draft.config : null,
  };
}
