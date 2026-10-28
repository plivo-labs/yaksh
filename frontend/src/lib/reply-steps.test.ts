import { expect, test } from "bun:test";

import { latency } from "@/lib/format";
import { inOrder, stepLabel } from "@/lib/reply-steps";

test("a reply's parts come in the order they happen, a new part last", () => {
  const stored: [string, number][] = [
    ["pipeline", 40],
    ["new_part", 5],
    ["llm_inference", 700],
    ["endpointing_wait", 600],
  ];
  expect(inOrder(stored).map(([key]) => key)).toEqual([
    "endpointing_wait",
    "llm_inference",
    "pipeline",
    "new_part",
  ]);
  expect(stepLabel("new_part")).toBe("new part");
});

test("a latency under a second is in ms, a longer one in seconds", () => {
  expect(latency(820)).toBe("820ms");
  expect(latency(999.6)).toBe("1.0s");
  expect(latency(1000)).toBe("1.0s");
  expect(latency(2140)).toBe("2.1s");
});
