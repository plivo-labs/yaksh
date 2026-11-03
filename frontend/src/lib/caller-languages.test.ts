import { expect, test } from "bun:test";

import { callerLanguages } from "@/lib/types";

test("a caller's languages name the primary one first, then the others", () => {
  expect(callerLanguages("en", [])).toBe("English");
  expect(callerLanguages("en", ["hi"])).toBe("English + Hindi");
  expect(callerLanguages("hi", ["mr", "en"])).toBe("Hindi + Marathi, English");
});
