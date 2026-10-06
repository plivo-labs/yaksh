import { isSameDay } from "date-fns";
import { CalendarIcon } from "lucide-react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { type Dates, PRESETS } from "@/hooks/use-dates-param";
import { cn } from "@/lib/utils";

const DAYS = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

function label(dates: Dates | undefined): string {
  if (!dates) return "All dates";
  if ("preset" in dates) return dates.preset.label;
  return DAYS.formatRange(dates.range.from, dates.range.to);
}

/** A preset applies at once. A range applies when its second day is picked, and a single picked
 * day applies when the popover closes. */
export function DateFilter({
  dates,
  onDatesChange,
  className,
}: {
  dates: Dates | undefined;
  onDatesChange: (dates: Dates | undefined) => void;
  className?: string;
}) {
  const range = dates && "range" in dates ? dates.range : undefined;
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateRange | undefined>(range);
  const today = new Date();

  const apply = (next: Dates | undefined) => {
    setDraft(next && "range" in next ? next.range : undefined);
    onDatesChange(next);
    setOpen(false);
  };
  const changeOpen = (next: boolean) => {
    if (next) setDraft(range);
    else if (draft?.from && !draft.to)
      onDatesChange({ range: { from: draft.from, to: draft.from } });
    setOpen(next);
  };
  const select = (next: DateRange | undefined) => {
    setDraft(next);
    if (next?.from && next.to) apply({ range: { from: next.from, to: next.to } });
  };

  const choices = [
    {
      label: "Today",
      current: range !== undefined && isSameDay(range.from, today) && isSameDay(range.to, today),
      dates: { range: { from: today, to: today } },
    },
    ...PRESETS.map((preset) => ({
      label: preset.label,
      current: dates !== undefined && "preset" in dates && dates.preset.value === preset.value,
      dates: { preset },
    })),
  ];

  return (
    <Popover open={open} onOpenChange={changeOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            aria-label="Filter by date"
            className={cn("justify-start", !dates && "text-muted-foreground", className)}
          />
        }
      >
        <CalendarIcon data-icon="inline-start" />
        {label(dates)}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto flex-row gap-0 p-0">
        <div className="flex w-36 flex-col gap-1 border-r p-2">
          <nav className="flex flex-col gap-1" aria-label="Date presets">
            {choices.map((choice) => (
              <Button
                key={choice.label}
                variant={choice.current ? "tertiary" : "ghost"}
                size="sm"
                aria-current={choice.current || undefined}
                className="justify-start"
                onClick={() => apply(choice.dates)}
              >
                {choice.label}
              </Button>
            ))}
          </nav>
          {dates && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-auto justify-start text-muted-foreground"
              onClick={() => apply(undefined)}
            >
              Clear dates
            </Button>
          )}
        </div>
        <Calendar
          mode="range"
          required
          resetOnSelect
          numberOfMonths={2}
          defaultMonth={range?.from ?? today}
          endMonth={today}
          disabled={{ after: today }}
          selected={draft}
          onSelect={select}
        />
      </PopoverContent>
    </Popover>
  );
}
