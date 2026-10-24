import type { EvaluationItem } from "@/lib/types";

type TurnQuote = { turn: number; quote: string };

export type SavedValueResult = {
  name: string;
  result: "matches" | "contradicts" | "not_checkable";
  evidence: TurnQuote[];
  reasoning: string;
};

export type HeardValueResult = {
  value: string;
  said: TurnQuote;
  heard: { line: number; quote: string } | null;
  result: "same" | "different" | "missing";
  reasoning: string;
};

/** Yaksh keeps an answer that failed the code checks as the judge gave it, so any field can be
 * missing. Its error reason stays when the caller check or a label changes the outcome. */
export function passedChecks(item: EvaluationItem): boolean {
  return item.error_reason === null;
}

export function checkedValues<T>(item: EvaluationItem | undefined): T[] | null {
  if (!item || !passedChecks(item)) return null;
  const values = item.answer?.values;
  return Array.isArray(values) ? (values as T[]) : null;
}
