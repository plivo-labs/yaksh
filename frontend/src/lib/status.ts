import type { ConversationStatus, RunResult, RunStatus } from "@/lib/types";

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

export const RESULT_TONE: Record<RunResult, Tone> = {
  running: "green",
  judging: "amber",
  passed: "green",
  failed: "red",
  not_decided: "amber",
  cancelled: "off",
};

export const RUN_TONE: Record<RunStatus, Tone> = {
  queued: "amber",
  running: "green",
  cancelling: "amber",
  done: "green",
  cancelled: "off",
};
