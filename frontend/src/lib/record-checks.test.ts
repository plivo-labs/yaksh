import { expect, test } from "bun:test";

import { checkedValues } from "@/lib/record-checks";
import type { EvaluationItem, Outcome } from "@/lib/types";

function item(
  machine: Outcome,
  effective: Outcome,
  values: unknown,
  error: string | null = machine === "error" ? "invalid_evidence" : null,
): EvaluationItem {
  return {
    item_key: "saved_data",
    subject: "Data the agent saved",
    role: "deciding",
    decided_by: "llm",
    machine_outcome: machine,
    unsure_kind: null,
    effective_outcome: effective,
    effective_unsure_kind: null,
    answer: { values },
    error_reason: error,
    caller_effect: null,
    jev_choice: null,
    jev_probabilities: null,
  };
}

test("a checked answer gives its values", () => {
  const values = [{ name: "caller_age", result: "matches", evidence: [], reasoning: "" }];
  expect(checkedValues(item("pass", "pass", values))).toEqual(values);
});

test("an answer that failed the code checks gives none, whatever outcome it ends with", () => {
  expect(checkedValues(item("error", "pass", {}))).toBeNull();
  expect(checkedValues(item("error", "error", [{ name: "caller_age" }]))).toBeNull();
  expect(checkedValues(item("blocked", "blocked", [null], "invalid_evidence"))).toBeNull();
});
