/** The parts of a caller reply, as Pipecat's latency breakdown names them: their labels and the
 * stage of the reply each belongs to. */

export type Stage = "turn" | "llm" | "speech" | "other";

const LABELS: Record<string, string> = {
  endpointing_wait: "Silence wait",
  first_request: "First request",
  transcription: "Transcript",
  turn_detection: "End-of-turn check",
  llm_inference: "LLM inference",
  turn_completion: "Turn completion",
  waiting_for_user: "Waiting for the agent",
  llm_tool_call: "LLM tool call",
  function_handler: "Tool",
  awaiting_speakable_text: "Waiting for words",
  sentence_aggregation: "Waiting for a sentence",
  speech_synthesis: "Speech synthesis",
  output_transport: "Output",
  pipeline: "Not attributed",
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

/** A part's colour on the reply's bar: one per stage, from the chart palette. */
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
  return LABELS[key] ?? key.replaceAll("_", " ");
}

/** A part that a later Pipecat adds is "other" until it is named here. */
export function stepStage(key: string): Stage {
  return STAGES[key] ?? "other";
}

const ORDER = Object.keys(LABELS);

/** A reply's parts in the order they happen, a part that a later Pipecat adds after the known
 * ones, by name; the database keeps them in its own order. */
export function inOrder<T>(entries: [string, T][]): [string, T][] {
  const place = (key: string) => {
    const at = ORDER.indexOf(key);
    return at === -1 ? ORDER.length : at;
  };
  return [...entries].sort(([a], [b]) => place(a) - place(b) || a.localeCompare(b));
}
