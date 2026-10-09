import { Plus } from "lucide-react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Scenario } from "@/lib/types";

/** A dashed "Add scenario" button that searches the given scenarios and adds the one chosen. */
export function ScenarioAdder({
  scenarios,
  onAdd,
}: {
  scenarios: Scenario[];
  onAdd: (scenario: Scenario) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const search = query.trim().toLowerCase();
  const choices = scenarios.filter((scenario) => scenario.name.toLowerCase().includes(search));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            disabled={scenarios.length === 0}
            className="flex h-12 w-full items-center justify-center gap-1.5 rounded-sm border border-dashed text-s-400 text-muted-foreground hover:bg-hv1 hover:text-foreground disabled:opacity-50"
          />
        }
      >
        <Plus className="size-3.5" />
        Add scenario
      </PopoverTrigger>
      <PopoverContent align="center" className="w-96 gap-0 p-0">
        <input
          aria-label="Search scenarios"
          placeholder="Search scenarios"
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="h-9 border-b bg-transparent px-3 text-p-400 outline-none placeholder:text-muted-foreground"
        />
        <ul className="max-h-72 overflow-y-auto p-1">
          {choices.length === 0 && (
            <li className="px-2.5 py-2 text-s-400 text-muted-foreground">No scenario matches.</li>
          )}
          {choices.map((scenario) => (
            <li key={scenario.id}>
              <button
                type="button"
                className="w-full truncate rounded-md px-2.5 py-1.5 text-left text-s-400 hover:bg-accent"
                onClick={() => {
                  onAdd(scenario);
                  setOpen(false);
                  setQuery("");
                }}
              >
                {scenario.name}
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
