import { addDays, format, isValid, parse } from "date-fns";

import { useFilterParams } from "@/hooks/use-filter-params";
import type { RunFilters } from "@/lib/queries";

const DAY = "yyyy-MM-dd";

export const PRESETS = [
  { value: "24h", label: "Last 24 hours", hours: 24 },
  { value: "7d", label: "Last 7 days", hours: 24 * 7 },
  { value: "30d", label: "Last 30 days", hours: 24 * 30 },
] as const;

export type Preset = (typeof PRESETS)[number];

/** Days picked on the calendar, or a period that ends now. Undefined means all dates. */
export type Dates = { range: { from: Date; to: Date } } | { preset: Preset };

function day(value: string | null): Date | undefined {
  if (!value) return undefined;
  const date = parse(value, DAY, new Date());
  return isValid(date) ? date : undefined;
}

/** The dates in the URL: `last` for a preset, or the days `from` and `to`, both included, in the
 * viewer's time zone, in order. */
export function useDatesParam() {
  const [params, update] = useFilterParams();
  const preset = PRESETS.find((item) => item.value === params.get("last"));
  const first = day(params.get("from"));
  const last = day(params.get("to")) ?? first;
  let dates: Dates | undefined;
  if (preset) dates = { preset };
  else if (first && last) {
    dates = { range: first <= last ? { from: first, to: last } : { from: last, to: first } };
  }

  const setDates = (next: Dates | undefined) =>
    update({
      last: next && "preset" in next ? next.preset.value : null,
      from: next && "range" in next ? format(next.range.from, DAY) : null,
      to: next && "range" in next ? format(next.range.to, DAY) : null,
    });

  return [dates, setDates] as const;
}

/** The run filters for the dates. Days run from the first day's midnight up to the midnight
 * after the last day. */
export function createdBetween(dates: Dates | undefined): RunFilters {
  if (!dates) return {};
  if ("preset" in dates) return { lastHours: dates.preset.hours };
  return {
    createdFrom: dates.range.from.toISOString(),
    createdBefore: addDays(dates.range.to, 1).toISOString(),
  };
}
