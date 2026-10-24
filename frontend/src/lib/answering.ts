import {
  type AfterScreening,
  type AgentRule,
  type AnsweredBy,
  type Answering,
  type Conversation,
  END_REASON_LABELS,
  type MachineLine,
  type ScreenerKind,
  type Turn,
  type VoicemailKind,
  type WireEvent,
} from "@/lib/types";

export const DEFAULT_ANSWERING: Answering = {
  voicemail: "iphone",
  greeting: null,
  screener: "iphone",
  after_screening: "picks_up",
};

export const ANSWERS: { value: AnsweredBy; label: string; description: string }[] = [
  { value: "caller", label: "The caller", description: "The persona answers and talks." },
  {
    value: "voicemail",
    label: "Voicemail",
    description: "Each persona's voicemail answers. It does not follow the scenario.",
  },
  {
    value: "screener",
    label: "Call screener",
    description: "Each persona's screener answers first.",
  },
];

export const VOICEMAILS: {
  value: VoicemailKind;
  label: string;
  description: string;
  /** The sound file of its standard greeting. */
  greeting: string;
  tone: boolean;
}[] = [
  {
    value: "iphone",
    label: "iPhone voicemail",
    description: "A greeting, a tone, then it records.",
    greeting: "answering/iphone_greeting.wav",
    tone: true,
  },
  {
    value: "pixel",
    label: "Pixel voicemail",
    description: "Take a Message: a greeting, a tone, then it records.",
    greeting: "answering/pixel_greeting.wav",
    tone: true,
  },
  {
    value: "carrier",
    label: "Carrier voicemail",
    description: "The network's voicemail, with a tone.",
    greeting: "answering/carrier_greeting.wav",
    tone: true,
  },
  {
    value: "carrier_no_tone",
    label: "Carrier voicemail, no tone",
    description: "It starts to record with no tone.",
    greeting: "answering/carrier_greeting.wav",
    tone: false,
  },
  {
    value: "mailbox_full",
    label: "Mailbox full",
    description: "A system line, then it hangs up.",
    greeting: "answering/mailbox_full.wav",
    tone: false,
  },
];

export const TONE_FILE = "answering/tone.wav";

export const SCREENERS: { value: ScreenerKind; label: string; description: string }[] = [
  {
    value: "iphone",
    label: "iPhone call screening",
    description: "Asks for a name and reason, then holds.",
  },
  {
    value: "pixel_call_assist",
    label: "Pixel Call Assist",
    description: "Asks why you call and can ask more.",
  },
  {
    value: "google_2018",
    label: "Google Call Screen (2018)",
    description: "The older Google greeting.",
  },
  { value: "samsung", label: "Samsung call screening", description: "Asks for a name and reason." },
  {
    value: "truecaller",
    label: "Truecaller Assistant",
    description: "Asks who is calling and why. Ends at 2 minutes.",
  },
];

export const AFTER_SCREENING: { value: AfterScreening; label: string; description: string }[] = [
  {
    value: "picks_up",
    label: "Picks up",
    description: "Talks with the agent, as the scenario says.",
  },
  {
    value: "voicemail",
    label: "Sends it to voicemail",
    description: "The voicemail above answers: greeting, tone, recording.",
  },
  {
    value: "reply",
    label: "Sends a reply",
    description: "The screener says one of its replies, then hangs up.",
  },
  {
    value: "declines",
    label: "Declines",
    description: "The screener hangs up while the agent waits.",
  },
];

export function voicemailOf(kind: VoicemailKind) {
  return VOICEMAILS.find((item) => item.value === kind) ?? VOICEMAILS[0];
}

export function screenerOf(kind: ScreenerKind) {
  return SCREENERS.find((item) => item.value === kind) ?? SCREENERS[0];
}

/** Who spoke a recorded line. */
export function machineSpeaker(line: MachineLine): string {
  return line === "screener" || line === "reply" ? "Call screener" : "Voicemail";
}

/** The band a piece of machine audio gets on the recording. */
export function machineBand(line: MachineLine): string {
  switch (line) {
    case "screener":
      return "Screener";
    case "reply":
      return "Reply";
    case "tone":
      return "Tone";
    default:
      return "Greeting";
  }
}

/** Whether the persona talks on a call with this answer, so the scenario's criteria apply. */
export function playsScenario(answeredBy: AnsweredBy, answering: Answering | null): boolean {
  return (
    answeredBy === "caller" ||
    (answeredBy === "screener" && answering?.after_screening === "picks_up")
  );
}

/** A line between the turns of the transcript: the tone, the hold, the persona picking up after
 * its screener, or how its voicemail or screener ended the call. Times count from the dial. */
export interface CallMoment {
  at_ms: number;
  text: string;
}

export function callMoments(
  conversation: Pick<Conversation, "wire_events" | "end_reason" | "caller_reason" | "talk_ms">,
  connectedMs: number,
): CallMoment[] {
  const moments = conversation.wire_events.flatMap((event): CallMoment[] => {
    switch (event.kind) {
      case "caller_sound":
        return event.detail
          ? [{ at_ms: event.at_ms, text: event.detail[0].toUpperCase() + event.detail.slice(1) }]
          : [];
      case "hold_started":
        return [
          {
            at_ms: event.at_ms,
            text: event.detail ? `Hold, ${Math.round(Number(event.detail) / 1000)} s` : "Hold",
          },
        ];
      case "handover":
        return [{ at_ms: event.at_ms, text: "The caller picks up" }];
      default:
        return [];
    }
  });
  const end = conversation.end_reason;
  if ((end === "voicemail_ended" || end === "screener_ended") && conversation.talk_ms !== null) {
    moments.push({
      at_ms: connectedMs + conversation.talk_ms,
      text: (conversation.caller_reason ?? END_REASON_LABELS[end]).replace(/\.$/, ""),
    });
  }
  return moments;
}

/** The "Answered by" text of a call. For a screener, what followed it comes from what happened:
 * the persona picking up, the voicemail's greeting, or the screener's reply. */
export function answeredText(
  answeredBy: AnsweredBy,
  answering: Answering | null,
  transcript: Turn[],
  events: WireEvent[],
): string {
  if (answeredBy === "caller" || answering === null) return "The caller";
  if (answeredBy === "voicemail") return `Voicemail, ${voicemailOf(answering.voicemail).label}`;
  const screener = `Call screener, ${screenerOf(answering.screener).label}`;
  if (events.some((event) => event.kind === "handover")) return `${screener}, then the caller`;
  const lines = transcript.map((turn) => turn.machine);
  if (lines.includes("greeting") || lines.includes("mailbox_full")) {
    return `${screener}, then voicemail`;
  }
  if (lines.includes("reply")) return `${screener}, then a reply`;
  return screener;
}

/** How long a sound of the persona's phone played, from its event's detail ("tone, 1 s"). */
export function soundMs(event: WireEvent): number {
  return Number(/([\d.]+) s$/.exec(event.detail ?? "")?.[1] ?? 0) * 1000;
}

/** Plain facts of a call that reached a voicemail: whether the agent spoke over its greeting,
 * and how long the agent spoke after the tone, or after the greeting when there is no tone. Null
 * when no greeting played, as with a full mailbox. */
export function voicemailFacts(
  transcript: Turn[],
  events: WireEvent[],
): { talkedOver: boolean; messageMs: number } | null {
  const greeting = transcript.find((turn) => turn.machine === "greeting");
  if (!greeting) return null;
  const agent = transcript.filter((turn) => turn.role === "agent");
  const tone = events.find((event) => event.kind === "caller_sound");
  const recording = tone ? tone.at_ms + soundMs(tone) : greeting.ended_at_ms;
  return {
    talkedOver: agent.some(
      (turn) =>
        turn.started_at_ms < greeting.ended_at_ms && turn.ended_at_ms > greeting.started_at_ms,
    ),
    messageMs: agent.reduce(
      (total, turn) =>
        total + Math.max(0, turn.ended_at_ms - Math.max(turn.started_at_ms, recording)),
      0,
    ),
  };
}

/** Whether the calls of an answer get no verdict: no rule that counts in the verdict checks
 * them. A call that the persona picks up after its screener is judged on the scenario's criteria,
 * so only the personas that do something else count. `personas` are the answering settings of the
 * personas of the scenario. */
export function withoutVerdict(
  answer: AnsweredBy,
  rules: AgentRule[],
  personas: Answering[],
): boolean {
  const decides = (reached: AnsweredBy[]) =>
    rules.some(
      (rule) =>
        rule.role === "deciding" &&
        (rule.answered_by === "any" || reached.includes(rule.answered_by)),
    );
  switch (answer) {
    case "caller":
      return false;
    case "voicemail":
      return !decides(["voicemail"]);
    case "screener":
      return personas.some((persona) => {
        if (persona.after_screening === "picks_up") return false;
        const after: AnsweredBy[] = persona.after_screening === "voicemail" ? ["voicemail"] : [];
        return !decides(["screener", ...after]);
      });
  }
}
