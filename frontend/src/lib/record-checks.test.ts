import { expect, test } from "bun:test";

import { checkedValues } from "@/lib/record-checks";
import type { EvaluationItem, Outcome } from "@/lib/types";

function item(machine: Outcome, effective: Outcome, values: unknown): EvaluationItem {
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
    error_reason: machine === "error" ? "invalid_evidence" : null,
    caller_effect: null,
    jev_choice: null,
    jev_probabilities: null,
  };
}

test("a checked answer gives its values", () => {
  const values = [{ name: "caller_age", result: "matches", evidence: [], reasoning: "" }];
  expect(checkedValues(item("pass", "pass", values))).toEqual(values);
});

test("an answer that failed the code checks gives none, even after a label passed it", () => {
  expect(checkedValues(item("error", "pass", {}))).toBeNull();
  expect(checkedValues(item("error", "error", [{ name: "caller_age" }]))).toBeNull();
});
