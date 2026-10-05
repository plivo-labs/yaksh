import type { ConversationStatus, Outcome, RunStatus, Verdict } from "@/lib/types";

export type Tone = "amber" | "green" | "red" | "off";

export const CONVERSATION_TONE: Record<ConversationStatus, Tone> = {
  queued: "amber",
  running: "green",
  ending: "amber",
  completed: "green",
  failed: "red",
  invalid: "red",
  cancelled: "off",
};

export const RUN_TONE: Record<RunStatus, Tone> = {
  queued: "amber",
  running: "green",
  cancelling: "amber",
  done: "green",
  cancelled: "off",
};

export const OUTCOME_TONE: Record<Outcome, Tone> = {
  pass: "green",
  fail: "red",
  not_applicable: "off",
  unsure: "amber",
  blocked: "amber",
  error: "red",
  pending: "amber",
};

export const VERDICT_TONE: Record<Verdict, Tone> = {
  pass: "green",
  fail: "red",
  not_scored: "amber",
};
