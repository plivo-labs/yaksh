/** The parts of a caller reply, as Pipecat's latency breakdown names them: their labels and the
 * stage of the reply each belongs to. */

export type Stage = "turn" | "llm" | "speech" | "other";

/** Each part's label and what it measures, in Voice AI terms, in the order the parts happen. */
const PARTS: Record<string, { label: string; tip: string }> = {
  endpointing_wait: {
    label: "VAD endpointing",
    tip: "Silence the VAD waits for before it reports that the agent stopped speaking (stop_secs).",
  },
  first_request: { label: "First request", tip: "Pipeline ready to the first LLM request." },
  transcription: {
    label: "STT after VAD stop",
    tip: "Wait past the VAD stop for the final STT transcript. 0 when the transcript was already final.",
  },
  turn_detection: {
    label: "Turn detection",
    tip: "Smart-turn model deciding the agent's turn is complete. Long when it sees the turn as incomplete.",
  },
  llm_inference: {
    label: "LLM TTFT",
    tip: "Caller LLM request to the first text token of the answer. Reasoning time is inside it.",
  },
  turn_completion: { label: "Turn completion", tip: "LLM turn-completion marker." },
  waiting_for_user: { label: "Waiting for the agent", tip: "LLM holding for the agent to go on." },
  llm_tool_call: { label: "LLM tool call", tip: "The LLM emitting a tool call, such as end_call." },
  function_handler: { label: "Tool execution", tip: "The tool handler running." },
  awaiting_speakable_text: {
    label: "Awaiting speakable text",
    tip: "LLM output that TTS cannot speak yet.",
  },
  sentence_aggregation: {
    label: "Sentence aggregation",
    tip: "Buffering LLM tokens until the first sentence is complete for TTS.",
  },
  speech_synthesis: { label: "TTS TTFB", tip: "TTS request to the first audio chunk." },
  output_transport: {
    label: "Output transport",
    tip: "First TTS audio chunk to the first audio frame sent on the call.",
  },
  pipeline: { label: "Unattributed", tip: "Pipeline time that no stage covers." },
};

/** The STT's TTFS for the agent's turn: shown beside the parts, as it overlaps them. */
export const STT_TTFS = {
  label: "STT TTFS",
  tip: "Agent speech end to the final STT transcript, below 0 when the transcript came first. Overlaps VAD endpointing: it adds to the reply only past the VAD stop.",
};

const STAGES: Record<string, Stage> = {
  endpointing_wait: "turn",
  first_request: "turn",
  transcription: "turn",
  turn_detection: "turn",
  llm_inference: "llm",
  turn_completion: "llm",
  waiting_for_user: "llm",
  llm_tool_call: "llm",
  function_handler: "llm",
  awaiting_speakable_text: "llm",
  sentence_aggregation: "speech",
  speech_synthesis: "speech",
};

/** A part's color on the reply's bar: one per stage, from the chart palette. */
export const STAGE_FILL: Record<Stage, string> = {
  turn: "bg-chart-category-2",
  llm: "bg-chart-category-1",
  speech: "bg-chart-category-4",
  other: "bg-chart-neutral",
};

/** The least a part takes to be shown, as the conversation's metric counts it: Pipecat counts a
 * hop between frames that is shorter as "pipeline". */
export const SHOWN_PART_MS = 5;

export function stepLabel(key: string): string {
  return PARTS[key]?.label ?? key.replaceAll("_", " ");
}

/** What a part measures; empty for a part that a later Pipecat adds. */
export function stepTip(key: string): string {
  return PARTS[key]?.tip ?? "";
}

/** A part that a later Pipecat adds is "other" until it is named here. */
export function stepStage(key: string): Stage {
  return STAGES[key] ?? "other";
}

const ORDER = Object.keys(PARTS);

/** A reply's parts in the order they happen, a part that a later Pipecat adds after the known
 * ones, by name; the database keeps them in its own order. */
export function inOrder<T>(entries: [string, T][]): [string, T][] {
  const place = (key: string) => {
    const at = ORDER.indexOf(key);
    return at === -1 ? ORDER.length : at;
  };
  return [...entries].sort(([a], [b]) => place(a) - place(b) || a.localeCompare(b));
}
