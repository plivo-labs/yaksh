import { beforeEach, expect, test } from "bun:test";

import { readStoredDraft, startImportedDraft } from "@/lib/new-agent-draft";

beforeEach(() => {
  const items = new Map<string, string>();
  globalThis.sessionStorage = {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  } as Storage;
});

test("an import with no language that Yaksha knows leaves the choice to the person", () => {
  startImportedDraft({ languages: [] }, { source: "Retell", kind: "retell" }, "brief-1");

  expect(readStoredDraft()?.draft.languages).toEqual([]);
});

test("a stored language that Yaksha no longer has is dropped, and the others stay in order", () => {
  startImportedDraft(
    { languages: ["hi", "xx" as never, "en-IN"] },
    { source: "file.json", kind: "file" },
    "brief-2",
  );

  expect(readStoredDraft()?.draft.languages).toEqual(["hi", "en-IN"]);
});
