import { CalendarIcon } from "lucide-react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const DAYS = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

/** The range applies when its second day is picked. A single picked day applies when the
 * popover closes. */
export function DateRangeFilter({
  range,
  onRangeChange,
  className,
}: {
  range: DateRange | undefined;
  onRangeChange: (range: DateRange | undefined) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(range);
  const today = new Date();

  const changeOpen = (next: boolean) => {
    if (next) setDraft(range);
    else if (draft?.from && !draft.to) onRangeChange({ from: draft.from, to: draft.from });
    setOpen(next);
  };
  const select = (next: DateRange | undefined) => {
    setDraft(next);
    if (next?.to) {
      onRangeChange(next);
      setOpen(false);
    }
  };
  const clear = () => {
    setDraft(undefined);
    onRangeChange(undefined);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={changeOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            aria-label="Filter by date"
            className={cn("justify-start", !range && "text-muted-foreground", className)}
          />
        }
      >
        <CalendarIcon data-icon="inline-start" />
        {range?.from ? DAYS.formatRange(range.from, range.to ?? range.from) : "All dates"}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto gap-0 p-0">
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
        {range && (
          <div className="flex justify-end border-t p-2">
            <Button variant="ghost" size="sm" onClick={clear}>
              Clear dates
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
