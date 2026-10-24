import { expect, test } from "bun:test";

import {
  DEFAULT_ANSWERING,
  answeredText,
  callMoments,
  voicemailFacts,
  withoutVerdict,
} from "@/lib/answering";
import type { AgentRule, MachineLine, Turn, WireEvent } from "@/lib/types";

function turn(
  role: Turn["role"],
  start: number,
  end: number,
  machine: MachineLine | null = null,
): Turn {
  return {
    role,
    text: "...",
    started_at_ms: start,
    ended_at_ms: end,
    provenance: null,
    scripted: false,
    machine,
    tools: [],
  };
}

const TONE: WireEvent = { kind: "caller_sound", at_ms: 7_000, detail: "tone, 1 s" };

function rule(answeredBy: AgentRule["answered_by"], role: AgentRule["role"]): AgentRule {
  return {
    kind: "phrase",
    key: "brand",
    name: "Names the company",
    expects: "required",
    match: "phrase",
    value: "Swift Movers",
    where: "any_agent_turn",
    role,
    answered_by: answeredBy,
  };
}

test("a voicemail's message counts from the tone, and words over the greeting are talk-over", () => {
  const transcript = [
    turn("caller", 1_000, 6_500, "greeting"),
    turn("agent", 2_000, 3_000),
    turn("agent", 8_500, 27_500),
  ];

  expect(voicemailFacts(transcript, [TONE])).toEqual({ talkedOver: true, messageMs: 19_000 });
});

test("speech over the tone is not part of the message", () => {
  const transcript = [turn("caller", 1_000, 6_500, "greeting"), turn("agent", 7_100, 7_900)];

  expect(voicemailFacts(transcript, [TONE])).toEqual({ talkedOver: false, messageMs: 0 });
});

test("with no tone the message counts from the end of the greeting", () => {
  const transcript = [turn("caller", 1_000, 6_000, "greeting"), turn("agent", 5_000, 9_000)];

  expect(voicemailFacts(transcript, [])).toEqual({ talkedOver: true, messageMs: 3_000 });
});

test("an agent that leaves no message has a message of no length, and a full mailbox has no facts", () => {
  expect(voicemailFacts([turn("caller", 1_000, 6_000, "greeting")], [TONE])).toEqual({
    talkedOver: false,
    messageMs: 0,
  });
  expect(voicemailFacts([turn("caller", 1_000, 6_000, "mailbox_full")], [])).toBeNull();
});

test("a screened call says what answered after the screener, from what happened", () => {
  const answering = { ...DEFAULT_ANSWERING, after_screening: "voicemail" as const };
  const screened = [turn("caller", 0, 1, "screener")];

  expect(answeredText("caller", null, [], [])).toBe("The caller");
  expect(answeredText("voicemail", DEFAULT_ANSWERING, [], [])).toBe("Voicemail, iPhone voicemail");
  expect(answeredText("screener", answering, screened, [])).toBe(
    "Call screener, iPhone call screening",
  );
  expect(
    answeredText("screener", answering, [...screened, turn("caller", 2, 3, "greeting")], []),
  ).toBe("Call screener, iPhone call screening, then voicemail");
  expect(
    answeredText("screener", DEFAULT_ANSWERING, screened, [
      { kind: "handover", at_ms: 5, detail: null },
    ]),
  ).toBe("Call screener, iPhone call screening, then the caller");
});

test("a voicemail answer gets no verdict without a deciding rule that checks voicemail", () => {
  const personas = [DEFAULT_ANSWERING];

  expect(withoutVerdict("voicemail", [], personas)).toBe(true);
  expect(withoutVerdict("voicemail", [rule("voicemail", "reporting")], personas)).toBe(true);
  expect(withoutVerdict("voicemail", [rule("caller", "deciding")], personas)).toBe(true);
  expect(withoutVerdict("voicemail", [rule("voicemail", "deciding")], personas)).toBe(false);
  expect(withoutVerdict("voicemail", [rule("any", "deciding")], personas)).toBe(false);
  expect(withoutVerdict("caller", [], personas)).toBe(false);
});

test("a screener answer needs a deciding rule only for personas that do not pick up", () => {
  const declines = { ...DEFAULT_ANSWERING, after_screening: "declines" as const };
  const toVoicemail = { ...DEFAULT_ANSWERING, after_screening: "voicemail" as const };

  expect(withoutVerdict("screener", [], [DEFAULT_ANSWERING])).toBe(false);
  expect(withoutVerdict("screener", [], [DEFAULT_ANSWERING, declines])).toBe(true);
  expect(withoutVerdict("screener", [rule("screener", "deciding")], [declines])).toBe(false);
  expect(withoutVerdict("screener", [rule("voicemail", "deciding")], [toVoicemail])).toBe(false);
  expect(withoutVerdict("screener", [rule("voicemail", "deciding")], [declines])).toBe(true);
});

test("the transcript shows the tone, the hold, the pickup and how a machine ended the call", () => {
  const events: WireEvent[] = [
    { kind: "connected", at_ms: 1_000, detail: null },
    TONE,
    { kind: "hold_started", at_ms: 9_000, detail: "14000" },
    { kind: "handover", at_ms: 23_000, detail: null },
  ];

  expect(
    callMoments(
      {
        wire_events: events,
        end_reason: "voicemail_ended",
        caller_reason: "The voicemail stopped recording after 5 s of silence.",
        talk_ms: 28_000,
      },
      1_000,
    ),
  ).toEqual([
    { at_ms: 7_000, text: "Tone, 1 s" },
    { at_ms: 9_000, text: "Hold, 14 s" },
    { at_ms: 23_000, text: "The caller picks up" },
    { at_ms: 29_000, text: "The voicemail stopped recording after 5 s of silence" },
  ]);
  expect(
    callMoments(
      { wire_events: [], end_reason: "agent_hangup", caller_reason: null, talk_ms: 5_000 },
      0,
    ),
  ).toEqual([]);
});
