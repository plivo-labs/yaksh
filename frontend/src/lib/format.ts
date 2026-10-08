import {
  type AgentSummary,
  NOISE_SOUND_LABELS,
  type OutcomeGroup,
  type SpeakerKind,
  type Surroundings,
} from "@/lib/types";

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

/** The year shows only when it is not the current year. */
export function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    year: date.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const SPEAKER_PHRASES: Record<SpeakerKind, string> = {
  talks_to_caller: "talks to the caller",
  own_phone_call: "on their own phone call",
  tv: "TV",
};

/** A level relative to the caller, as "−10 dB". */
export function decibels(db: number): string {
  return db === 0 ? "0 dB" : `${db > 0 ? "+" : "−"}${Math.abs(db)} dB`;
}

/** "Cafe and car, second speaker (TV)", or null for a quiet room. With `exact`, every setting
 * that tells two surroundings apart: "Cafe −10 dB, second speaker (TV) −6 dB from 5 s". */
export function surroundingsLabel(surroundings: Surroundings, exact = false): string | null {
  const level = (db: number) => (exact ? ` ${decibels(db)}` : "");
  const parts = [];
  if (surroundings.sounds.length > 0)
    parts.push(
      surroundings.sounds.map((s) => `${NOISE_SOUND_LABELS[s.sound]}${level(s.db)}`).join(" and "),
    );
  const { auto, speaker } = surroundings;
  if (auto) parts.push(`auto noise${level(auto.db)}${exact ? ` (mix ${auto.seed})` : ""}`);
  if (speaker)
    parts.push(
      `second speaker (${SPEAKER_PHRASES[speaker.kind]})${level(speaker.db)}${exact ? ` from ${speaker.start_s} s` : ""}`,
    );
  if (parts.length === 0) return null;
  const label = parts.join(", ");
  return label[0].toUpperCase() + label.slice(1);
}

export function words(value: string): string {
  return value.replaceAll("_", " ");
}

/** North American numbers in their spoken grouping; every other number as stored. */
export function phone(number: string): string {
  const parts = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(number);
  return parts ? `+1 ${parts[1]} ${parts[2]} ${parts[3]}` : number;
}

/** Whole seconds as m:ss, for time rulers. */
export function stamp(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** How Yaksha reaches an agent: the number it dials, or that the agent calls Yaksha. */
export function reach(agent: AgentSummary): string {
  return agent.agent_number ? phone(agent.agent_number) : "Calls Yaksha";
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

const FINISHED: OutcomeGroup[] = ["completed", "did_not_connect", "error", "cancelled"];

/** How many of a run's counted conversations are over, whatever their outcome. */
export function runFinished(run: { counts: Record<OutcomeGroup, number> }): number {
  return FINISHED.reduce((sum, group) => sum + run.counts[group], 0);
}

/** A wait with one decimal: 2.1s. */
export function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

export type ResponseBand = "good" | "slow" | "bad";

/** A band's color as text on the canvas. */
export const BAND_TEXT: Record<ResponseBand, string> = {
  good: "text-status-success-text",
  slow: "text-status-warning-text",
  bad: "text-status-danger-text",
};

/** A band as a tag: the pale fill and the dark ink of its hue. */
export const BAND_TAG: Record<ResponseBand, string> = {
  good: "bg-success-tag text-success-tag-foreground",
  slow: "bg-warning text-warning-foreground",
  bad: "bg-danger text-danger-foreground",
};

/** A band as a see-through wash over the waveform. */
export const BAND_WASH: Record<ResponseBand, string> = {
  good: "bg-status-success/15",
  slow: "bg-status-warning/15",
  bad: "bg-status-danger/15",
};

/** Under 1 s, 1 to 2 s, over 2 s. */
export function responseBand(ms: number): ResponseBand {
  if (ms < 1000) return "good";
  return ms <= 2000 ? "slow" : "bad";
}

/** A number's region with the country in title case: Plivo sends it in capitals, as in
 * "Illinois, UNITED STATES". */
export function region(text: string): string {
  const parts = text.split(", ");
  const country = parts[parts.length - 1];
  if (country !== country.toUpperCase()) return text;
  parts[parts.length - 1] = country
    .toLowerCase()
    .replace(/(^|\s)\p{L}/gu, (start) => start.toUpperCase());
  return parts.join(", ");
}

export function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
