import { addDays, format, isValid, parse } from "date-fns";
import type { DateRange } from "react-day-picker";
import { useSearchParams } from "react-router";

const DAY = "yyyy-MM-dd";

function day(value: string | null): Date | undefined {
  if (!value) return undefined;
  const date = parse(value, DAY, new Date());
  return isValid(date) ? date : undefined;
}

/** The days `from` and `to` in the URL, both included, in the viewer's time zone, in order. A
 * change goes back to the first page. */
export function useDateRangeParam() {
  const [params, setParams] = useSearchParams();
  const first = day(params.get("from"));
  const last = day(params.get("to")) ?? first;
  const range: DateRange | undefined =
    first && last && (first <= last ? { from: first, to: last } : { from: last, to: first });

  const setRange = (next: DateRange | undefined) => {
    const target = new URLSearchParams(params);
    target.delete("from");
    target.delete("to");
    if (next?.from) {
      target.set("from", format(next.from, DAY));
      target.set("to", format(next.to ?? next.from, DAY));
    }
    target.delete("page");
    setParams(target, { replace: true });
  };

  return [range, setRange] as const;
}

/** The range as the instants the API filters on: from the first day's midnight up to the
 * midnight after the last day. */
export function createdBetween(range: DateRange | undefined) {
  if (!range?.from) return {};
  return {
    createdFrom: range.from.toISOString(),
    createdBefore: addDays(range.to ?? range.from, 1).toISOString(),
  };
}
