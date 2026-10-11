import { expect, test } from "bun:test";

import { freeName } from "@/lib/names";

test("a taken name gets the next free number, within the limit", () => {
  const taken = new Set(["madrid", "madrid (2)"]);
  expect(freeName("Madrid", taken)).toBe("Madrid (3)");
  expect(freeName("Lisbon", taken)).toBe("Lisbon");
  expect(freeName("n".repeat(80), new Set(["n".repeat(80)]))).toBe(`${"n".repeat(76)} (2)`);
});
