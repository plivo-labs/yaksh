import { latency } from "@/lib/format";
import type { LineStop, Turn } from "@/lib/types";

/** The 2s in which the agent's speech must stop after a line's start to count as a stop. */
const WINDOW = "2s";

function time(stop: LineStop): string {
  return `${latency(stop.stop_ms ?? 0)}${stop.at_least ? "+" : ""}`;
}

/** The short label of a line's result, for its badge and its Metrics row. */
export function stopLabel(stop: LineStop): string {
  switch (stop.result) {
    case "stopped":
      return `Stopped in ${time(stop)}`;
    case "kept_talking":
      return `Kept talking ${time(stop)}`;
    case "not_speaking":
      return "Agent done speaking";
    case "unknown":
      return "Not measured";
  }
}

/** The result in a sentence: the tooltip of the badge, and the reason a line was not measured. */
export function stopHint(stop: LineStop): string {
  switch (stop.result) {
    case "stopped":
      return `The agent's speech stopped ${time(stop)} after the line started.`;
    case "kept_talking":
      if (!stop.at_least) {
        return `The agent spoke for ${time(stop)} after the line started. It did not stop within ${WINDOW}.`;
      }
      return `The agent spoke for at least ${latency(stop.stop_ms ?? 0)} after the line started. ${
        stop.reason === "recording_ended"
          ? "Then the recording ended."
          : "Then part of its audio is missing."
      }`;
    case "not_speaking":
      return "The agent was not speaking when the line started, or its speech ended less than 200ms after it: too soon to stop for the line.";
    case "unknown":
      switch (stop.reason) {
        case "recording_ended":
          return "The recording ended right after the agent's speech, so Yaksh cannot tell if it stopped.";
        case "no_line_speech":
          return "Yaksh found no speech in the part of the line that went out.";
        default:
          return "Part of the agent's audio is missing, so Yaksh cannot tell when it stopped.";
      }
  }
}

/** The hover text of a line's pin on the waveform. */
export function pinTitle(stop: LineStop): string {
  const result =
    stop.result === "stopped"
      ? `Agent stopped in ${time(stop)}`
      : stop.result === "kept_talking"
        ? `Agent kept talking ${time(stop)}`
        : stopLabel(stop);
  return `Line ${stop.number} · ${result}`;
}

/** One interruption line of a call as the Metrics tab lists it. */
export interface LineRow {
  number: number;
  /** The words of all the line's turns: a line that went out in part is two turns. */
  words: string;
  /** When the line's first turn started, on the call clock. */
  at_ms: number;
  stop: LineStop;
}

/** The lines with a stop result, in the order they played. The result is on each line's first
 * turn. */
export function lineRows(turns: Turn[]): LineRow[] {
  const rows = new Map<number, LineRow>();
  for (const turn of turns) {
    const number = turn.interruption;
    if (!number) continue;
    const row = rows.get(number);
    if (row) {
      row.words = `${row.words} ${turn.text}`;
    } else if (turn.agent_stop) {
      rows.set(number, {
        number,
        words: turn.text,
        at_ms: turn.started_at_ms,
        stop: turn.agent_stop,
      });
    }
  }
  return [...rows.values()];
}

/** "Stopped within 2s: 2 of 3", over the lines whose speech stopped in time or kept on; null
 * when no line was measured. */
export function stoppedSummary(rows: LineRow[]): string | null {
  const measured = rows.filter(
    (row) => row.stop.result === "stopped" || row.stop.result === "kept_talking",
  );
  if (measured.length === 0) return null;
  const stopped = measured.filter((row) => row.stop.result === "stopped").length;
  return `Stopped within ${WINDOW}: ${stopped} of ${measured.length}`;
}
