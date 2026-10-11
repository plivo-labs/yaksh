import { Plus, XIcon } from "lucide-react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { LANGUAGE_NAMES, type Language, type Persona } from "@/lib/types";

/** The personas of one list as chips, in the list's order, each with a button that removes it,
 * and an "Add" button that searches the other personas. Personas in a language outside `served`
 * are marked in the search list. */
export function PersonaChips({
  label,
  personas,
  value,
  served,
  invalid,
  onValueChange,
}: {
  label: string;
  personas: Persona[];
  value: string[];
  served: ReadonlySet<Language>;
  invalid?: boolean;
  onValueChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const byId = new Map(personas.map((persona) => [persona.id, persona]));
  const picked = value.flatMap((id) => byId.get(id) ?? []);
  const search = query.trim().toLowerCase();
  const choices = personas.filter(
    (persona) => !value.includes(persona.id) && persona.name.toLowerCase().includes(search),
  );
  const add = (id: string) => {
    onValueChange([...value, id]);
    setOpen(false);
    setQuery("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {picked.map((persona) => (
        <span
          key={persona.id}
          className="flex h-7 items-center gap-1 rounded-sm bg-bg1 pr-1 pl-2.5 text-xs-500"
        >
          {persona.name}
          <button
            type="button"
            aria-label={`Remove ${persona.name} from ${label}`}
            className="flex size-5 items-center justify-center rounded-sm text-muted-foreground hover:bg-hv2 hover:text-foreground"
            onClick={() => onValueChange(value.filter((id) => id !== persona.id))}
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
              aria-label={`Add a persona to ${label}`}
              aria-invalid={invalid || undefined}
              className={cn(
                "flex h-7 items-center gap-1 rounded-sm border border-dashed px-2.5 text-xs-500 text-muted-foreground hover:bg-hv1 hover:text-foreground",
                invalid && "border-destructive text-destructive",
              )}
            />
          }
        >
          <Plus className="size-3" />
          Add
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 gap-0 p-0">
          <input
            aria-label="Search personas"
            placeholder="Search personas"
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-9 border-b bg-transparent px-3 text-p-400 outline-none placeholder:text-muted-foreground"
          />
          <ul className="max-h-64 overflow-y-auto p-1">
            {choices.length === 0 && (
              <li className="px-2.5 py-2 text-s-400 text-muted-foreground">No persona matches.</li>
            )}
            {choices.map((persona) => (
              <li key={persona.id}>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-s-400 hover:bg-accent"
                  onClick={() => add(persona.id)}
                >
                  <span className="min-w-0 flex-1 truncate">{persona.name}</span>
                  <span
                    className={cn(
                      "shrink-0 text-xs-400",
                      served.has(persona.language)
                        ? "text-muted-foreground"
                        : "text-status-warning-text",
                    )}
                  >
                    {LANGUAGE_NAMES[persona.language]}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
    </div>
  );
}
