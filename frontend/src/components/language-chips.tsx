import { Plus, XIcon } from "lucide-react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { AGENT_LANGUAGE_CODES, AGENT_LANGUAGES, type AgentLanguage } from "@/lib/types";
import { cn } from "@/lib/utils";

/** An agent's languages as chips, in its order, each with a button that removes it, and an "Add"
 * button that lists the other languages. */
export function LanguageChips({
  id,
  value,
  invalid,
  onValueChange,
}: {
  id?: string;
  value: AgentLanguage[];
  invalid?: boolean;
  onValueChange: (languages: AgentLanguage[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const choices = AGENT_LANGUAGE_CODES.filter((code) => !value.includes(code));
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {value.map((code) => (
        <span
          key={code}
          className="flex h-7 items-center gap-1 rounded-sm bg-bg1 pr-1 pl-2.5 text-xs-500"
        >
          {AGENT_LANGUAGES[code].name}
          <button
            type="button"
            aria-label={`Remove ${AGENT_LANGUAGES[code].name}`}
            className="flex size-5 items-center justify-center rounded-sm text-muted-foreground hover:bg-hv2 hover:text-foreground"
            onClick={() => onValueChange(value.filter((other) => other !== code))}
          >
            <XIcon className="size-3" />
          </button>
        </span>
      ))}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <button
              type="button"
              id={id}
              aria-label="Add a language"
              aria-invalid={invalid || undefined}
              disabled={choices.length === 0}
              className={cn(
                "flex h-7 items-center gap-1 rounded-sm border border-dashed px-2.5 text-xs-500 text-muted-foreground hover:bg-hv1 hover:text-foreground disabled:opacity-50",
                invalid && "border-destructive text-destructive",
              )}
            />
          }
        >
          <Plus className="size-3" />
          Add
        </PopoverTrigger>
        <PopoverContent align="start" className="w-56 gap-0 p-1">
          <ul>
            {choices.map((code) => (
              <li key={code}>
                <button
                  type="button"
                  className="w-full rounded-md px-2.5 py-1.5 text-left text-s-400 hover:bg-accent"
                  onClick={() => {
                    onValueChange([...value, code]);
                    setOpen(false);
                  }}
                >
                  {AGENT_LANGUAGES[code].name}
                </button>
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
    </div>
  );
}
