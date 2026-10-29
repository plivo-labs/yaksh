import { expect, test } from "bun:test";

import { lineNotes, lineProblems } from "@/lib/interruptions";
import type { DataSet, Interruption, InterruptionTry, Turn, WireEvent } from "@/lib/types";

function turn(role: Turn["role"], start: number, end: number, interruption?: number): Turn {
  return {
    role,
    text: "...",
    started_at_ms: start,
    ended_at_ms: end,
    provenance: null,
    scripted: interruption !== undefined,
    machine: null,
    dtmf: false,
    tools: [],
    interruption: interruption ?? null,
  };
}

function attempt(
  at: number,
  number: number,
  started: number | null,
  reason: string | null = null,
  words: string | null = null,
) {
  const interruption: InterruptionTry = {
    number,
    reason,
    detail: null,
    turn_started_ms: started,
    words,
  };
  return { kind: "interruption", at_ms: at, detail: null, interruption } satisfies WireEvent;
}

test("each played line says how far into which agent turn the caller said it", () => {
  const turns = [
    turn("agent", 31_000, 36_000),
    turn("caller", 34_100, 35_600, 1),
    turn("agent", 9_400, 16_000),
    turn("caller", 14_000, 15_000, 2),
  ];
  const events = [
    attempt(33_000, 1, 31_000, "turn_ended"),
    attempt(34_100, 1, 31_000),
    attempt(14_000, 2, 9_000),
  ];

  expect(lineNotes(turns, events, 4_000)).toEqual(
    new Map([
      [1, "3.1 s into the agent's turn at 0:27.0"],
      [3, "4.6 s into the agent's turn at 0:05.4"],
    ]),
  );
});

test("a line over sound with no words names no agent turn", () => {
  const turns = [turn("agent", 1_000, 2_000), turn("caller", 3_000, 4_000, 1)];

  expect(lineNotes(turns, [attempt(3_000, 1, 2_500)], 0)).toEqual(
    new Map([[1, "Over sound with no words from the agent"]]),
  );
});

test("a line with no stored agent turn quotes the last words the agent said before it", () => {
  const turns = [turn("caller", 3_000, 4_000, 1)];
  const words = "the first visit includes a full exam X-rays and the cleaning and we also go over";

  expect(lineNotes(turns, [attempt(3_000, 1, 2_000, null, words)], 0)).toEqual(
    new Map([
      [0, "After the agent said “…a full exam X-rays and the cleaning and we also go over”"],
    ]),
  );
});

test("a line that the agent heard only in part is two turns, and only the first has the note", () => {
  const turns = [
    turn("agent", 1_000, 6_000),
    turn("caller", 3_000, 3_800, 1),
    turn("caller", 3_800, 3_800, 1),
  ];

  expect(lineNotes(turns, [attempt(3_000, 1, 1_000)], 0)).toEqual(
    new Map([[1, "2.0 s into the agent's turn at 0:01.0"]]),
  );
});

const near: DataSet = {
  name: "Near",
  known_facts: [{ name: "Address", value: "1 Main Street" }],
  agent_data: [],
};
const far: DataSet = {
  name: "Far",
  known_facts: [{ name: "Address", value: "Unit 4, ".repeat(24) }],
  agent_data: [],
};

function line(fields: Partial<Interruption>): Interruption {
  return {
    say: "Sorry, is that at {{Address}}?",
    agent_says: null,
    after_s: 2,
    from_answer: 2,
    ...fields,
  };
}

test("a line can save when it fits the limit with the facts of every data set", () => {
  expect(lineProblems(line({}), [near])).toEqual({
    phrase: null,
    wait: null,
    answer: null,
    say: null,
  });
  expect(lineProblems(line({}), [near, far]).say).toBe(
    "With the facts of Far, the line is longer than 200 characters.",
  );
  expect(lineProblems(line({}), [far]).say).toBe(
    "With the known facts, the line is longer than 200 characters.",
  );
});

test("a phrase needs a word or a number as the API reads them: letters, marks or digits", () => {
  const phrase = (agent_says: string) => lineProblems(line({ agent_says }), [near]).phrase;

  expect(phrase("1st visit")).toBeNull();
  expect(phrase("पहली")).toBeNull();
  expect(phrase("...")).toBe("Enter a phrase with a word or a number.");
  expect(phrase("½")).toBe("Enter a phrase with a word or a number.");
  expect(phrase("  ")).toBe("Enter a phrase.");
});

test("a wait or a first answer outside the API's ranges keeps the line from saving", () => {
  expect(lineProblems(line({ after_s: Number.NaN, from_answer: 1.5 }), [near])).toEqual({
    phrase: null,
    wait: "Enter a wait from 0 to 30 seconds.",
    answer: "Enter an answer from 1 to 100.",
    say: null,
  });
});
