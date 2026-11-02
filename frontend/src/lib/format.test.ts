import { expect, test } from "bun:test";

import { clock } from "@/lib/format";

test("a time before the call's start reads as minus its distance from the start", () => {
  expect(clock(-700)).toBe("-0:00.7");
  expect(clock(-61_200)).toBe("-1:01.2");
});

test("a time that rounds up to the next minute carries into the minutes", () => {
  expect(clock(59_960)).toBe("1:00.0");
  expect(clock(83_761)).toBe("1:23.8");
  expect(clock(0)).toBe("0:00.0");
});
