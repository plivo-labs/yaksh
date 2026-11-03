import { expect, test } from "bun:test";

import { lineRows, pinTitle, stopHint, stopLabel, stoppedSummary } from "@/lib/stops";
import type { LineStop, Turn } from "@/lib/types";

function stop(fields: Partial<LineStop>): LineStop {
  return {
    number: 1,
    line_ms: 2_000,
    result: "stopped",
    stop_ms: 841,
    at_least: false,
    reason: null,
    ...fields,
  };
}

function line(number: number, text: string, at: number, agentStop?: LineStop): Turn {
  return {
    role: "caller",
    text,
    started_at_ms: at,
    ended_at_ms: at + 500,
    provenance: "transmitted",
    scripted: true,
    machine: null,
    dtmf: false,
    tools: [],
    interruption: number,
    agent_stop: agentStop ?? null,
  };
}

test("each result has its badge label and its sentence", () => {
  const cases: [LineStop, string, string][] = [
    [stop({}), "Stopped in 841ms", "The agent's speech stopped 841ms after the line started."],
    [
      stop({ result: "kept_talking", stop_ms: 9_662 }),
      "Kept talking 9.7s",
      "The agent spoke for 9.7s after the line started. It did not stop within 2s.",
    ],
    [
      stop({ result: "kept_talking", stop_ms: 3_500, at_least: true, reason: "recording_ended" }),
      "Kept talking 3.5s+",
      "The agent spoke for at least 3.5s after the line started. Then the recording ended.",
    ],
    [
      stop({ result: "kept_talking", stop_ms: 3_000, at_least: true, reason: "media_gap" }),
      "Kept talking 3.0s+",
      "The agent spoke for at least 3.0s after the line started. Then part of its audio is missing.",
    ],
    [
      stop({ result: "not_speaking", stop_ms: null }),
      "Agent done speaking",
      "The agent was not speaking when the line started, or its speech ended less than 200ms after it: too soon to stop for the line.",
    ],
    [
      stop({ result: "unknown", stop_ms: null, reason: "media_gap" }),
      "Not measured",
      "Part of the agent's audio is missing, so Yaksh cannot tell when it stopped.",
    ],
    [
      stop({ result: "unknown", stop_ms: null, reason: "recording_ended" }),
      "Not measured",
      "The recording ended right after the agent's speech, so Yaksh cannot tell if it stopped.",
    ],
    [
      stop({ result: "unknown", line_ms: null, stop_ms: null, reason: "no_line_speech" }),
      "Not measured",
      "Yaksh found no speech in the part of the line that went out.",
    ],
  ];
  for (const [found, label, hint] of cases) {
    expect([stopLabel(found), stopHint(found)]).toEqual([label, hint]);
  }
});

test("a pin names its line and what the agent did", () => {
  expect(pinTitle(stop({ number: 2, result: "kept_talking", stop_ms: 9_662 }))).toBe(
    "Line 2 · Agent kept talking 9.7s",
  );
  expect(pinTitle(stop({ number: 3 }))).toBe("Line 3 · Agent stopped in 841ms");
  expect(pinTitle(stop({ result: "unknown", stop_ms: null, reason: "media_gap" }))).toBe(
    "Line 1 · Not measured",
  );
});

test("a line that went out in part is one row with the words of both turns", () => {
  const first = stop({ number: 1, stop_ms: 788 });
  const second = stop({ number: 2, result: "kept_talking", stop_ms: 9_662 });
  const agent: Turn = { ...line(1, "Your booking is", 0), role: "agent", interruption: null };

  const rows = lineRows([
    agent,
    line(1, "Sorry,", 2_000, first),
    line(1, "what time was that?", 2_400),
    agent,
    line(2, "Wait.", 12_000, second),
  ]);

  expect(rows).toEqual([
    { number: 1, words: "Sorry, what time was that?", at_ms: 2_000, stop: first },
    { number: 2, words: "Wait.", at_ms: 12_000, stop: second },
  ]);
});

test("a call measured before stop times has no rows", () => {
  expect(lineRows([line(1, "Sorry?", 2_000)])).toEqual([]);
});

test("the summary counts the lines that stopped in time over the lines measured", () => {
  const rows = lineRows([
    line(1, "a", 1_000, stop({ number: 1 })),
    line(2, "b", 5_000, stop({ number: 2, result: "kept_talking", stop_ms: 4_000 })),
    line(3, "c", 9_000, stop({ number: 3, result: "unknown", stop_ms: null, reason: "media_gap" })),
  ]);

  expect(stoppedSummary(rows)).toBe("Stopped within 2s: 1 of 2");
  expect(stoppedSummary(rows.slice(2))).toBeNull();
});
