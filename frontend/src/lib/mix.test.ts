import { expect, test } from "bun:test";

import { mixPersonas } from "@/lib/mix";

/** The same numbers every time, so a test failure can be read again. */
function seeded(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1103515245 + 12345) % 2147483648;
    return state / 2147483648;
  };
}

const pool = ["a", "b", "c", "d", "e", "f", "g", "h"];
const scenarios = [
  { id: "s1", persona_id: "a" },
  { id: "s2", persona_id: "b" },
  { id: "s3", persona_id: "b" },
];

test("each scenario keeps its own persona first and has no persona twice", () => {
  for (let seed = 1; seed < 50; seed++) {
    const mixed = mixPersonas(scenarios, pool, 3, seeded(seed));
    for (const scenario of scenarios) {
      const picked = mixed[scenario.id];
      expect(picked[0]).toBe(scenario.persona_id);
      expect(picked).toHaveLength(3);
      expect(new Set(picked).size).toBe(3);
    }
  }
});

test("every persona is dealt once before any is dealt twice", () => {
  for (let seed = 1; seed < 50; seed++) {
    const mixed = mixPersonas(scenarios, pool, 3, seeded(seed));
    const dealt = scenarios.flatMap((scenario) => mixed[scenario.id].slice(1));
    expect(new Set(dealt).size).toBe(dealt.length);
  }
});

test("scenarios that share their own persona still get the rest of the pool", () => {
  const same = [
    { id: "s1", persona_id: "a" },
    { id: "s2", persona_id: "a" },
  ];
  expect(mixPersonas(same, ["a", "b"], 2, seeded(3))).toEqual({ s1: ["a", "b"], s2: ["a", "b"] });
});

test("a pool smaller than asked gives each scenario what it has", () => {
  const mixed = mixPersonas(scenarios, ["a", "b"], 4, seeded(7));
  expect(mixed).toEqual({ s1: ["a", "b"], s2: ["b", "a"], s3: ["b", "a"] });
});
