import type { EvaluationItem } from "@/lib/types";

type TurnQuote = { turn: number; quote: string };

/** One saved value as the saved data check found it. */
export type SavedValueResult = {
  name: string;
  result: "matches" | "contradicts" | "not_checkable";
  evidence: TurnQuote[];
  reasoning: string;
};

/** One value the caller said, and what the agent's speech-to-text heard. */
export type HeardValueResult = {
  value: string;
  said: TurnQuote;
  heard: { line: number; quote: string } | null;
  result: "same" | "different" | "missing";
  reasoning: string;
};

/** The values of a record check's answer. None for an answer that failed the code checks:
 * Yaksh keeps that answer as the judge gave it, so any field can be missing. */
export function checkedValues<T>(item: EvaluationItem | undefined): T[] | null {
  if (!item || item.machine_outcome === "error") return null;
  const values = item.answer?.values;
  return Array.isArray(values) ? (values as T[]) : null;
}
