import type { AgentSummary, OutcomeGroup } from "@/lib/types";

export function clock(ms: number): string {
  const seconds = ms / 1000;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

export function duration(ms: number | null): string {
  if (ms === null) return "";
  const seconds = Math.round(ms / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function when(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function words(value: string): string {
  return value.replaceAll("_", " ");
}

/** North American numbers in their spoken grouping; every other number as stored. */
export function phone(number: string): string {
  const parts = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(number);
  return parts ? `+1 ${parts[1]} ${parts[2]} ${parts[3]}` : number;
}

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 7],
  ["week", 4.35],
  ["month", 12],
  ["year", Infinity],
];

export function since(iso: string): string {
  let amount = (new Date(iso).getTime() - Date.now()) / 1000;
  for (const [unit, size] of STEPS) {
    if (Math.abs(amount) < size) return RELATIVE.format(Math.round(amount), unit);
    amount /= size;
  }
  return "";
}

const EXACT = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" });

export function exact(iso: string): string {
  return EXACT.format(new Date(iso));
}

/** Whole seconds as m:ss, for time rulers. */
export function stamp(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** How Truman reaches an agent: the number it dials, or that the agent calls Truman. */
export function reach(agent: AgentSummary): string {
  return agent.agent_number ? phone(agent.agent_number) : "Calls Truman";
}

/** A text's length as the model sees it: about four characters per token in English. */
export function textSize(characters: number): string {
  const tokens = Math.round(characters / 4);
  return `${characters.toLocaleString()} characters, about ${tokens.toLocaleString()} tokens`;
}

/** A count with its noun, such as "1 scenario" or "3 scenarios". */
export function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** A run's name, or its creation time when it has none. */
export function runTitle(run: { name: string | null; created_at: string }): string {
  return run.name ?? `Run of ${when(run.created_at)}`;
}

/** How many conversations a run counts: the latest attempt of each repeat of each scenario. */
export function runTotal(run: { counts: Record<OutcomeGroup, number> }): number {
  return Object.values(run.counts).reduce((sum, count) => sum + count, 0);
}
