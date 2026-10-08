import { Combobox } from "@base-ui/react/combobox";
import { CheckIcon, XIcon } from "lucide-react";
import { useMemo, useRef } from "react";

import { LANGUAGE_NAMES, type Persona } from "@/lib/types";

const personaName = (persona: Persona) => persona.name;

/** Several personas, picked from a searchable list. The picked ones show as chips in the field,
 * each with a button that removes it. */
export function PersonaPicker({
  id,
  personas,
  value,
  onValueChange,
  invalid,
}: {
  id: string;
  personas: Persona[];
  value: string[];
  onValueChange: (ids: string[]) => void;
  invalid?: boolean;
}) {
  const anchor = useRef<HTMLDivElement | null>(null);
  const picked = useMemo(
    () => personas.filter((persona) => value.includes(persona.id)),
    [personas, value],
  );
  return (
    <Combobox.Root
      items={personas}
      multiple
      value={picked}
      onValueChange={(next: Persona[]) => onValueChange(next.map((persona) => persona.id))}
      itemToStringLabel={personaName}
      autoHighlight
    >
      <Combobox.Chips
        ref={anchor}
        className="flex min-h-9 w-full flex-wrap items-center gap-1 rounded-md border border-input bg-transparent px-1.5 py-1 focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 focus-within:ring-offset-background has-aria-invalid:border-destructive"
      >
        <Combobox.Value>
          {(selected: Persona[]) => (
            <>
              {selected.map((persona) => (
                <Combobox.Chip
                  key={persona.id}
                  className="flex h-6 items-center gap-1 rounded-sm bg-bg1 pr-0.5 pl-2 text-xs-500 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {persona.name}
                  <Combobox.ChipRemove
                    aria-label={`Remove ${persona.name}`}
                    className="flex size-5 items-center justify-center rounded-sm text-muted-foreground hover:bg-hv2 hover:text-foreground"
                  >
                    <XIcon className="size-3" />
                  </Combobox.ChipRemove>
                </Combobox.Chip>
              ))}
              <Combobox.Input
                id={id}
                aria-invalid={invalid || undefined}
                placeholder={selected.length === 0 ? "Search personas" : ""}
                className="h-6 min-w-24 flex-1 bg-transparent px-1 text-p-400 outline-none placeholder:text-muted-foreground"
              />
            </>
          )}
        </Combobox.Value>
      </Combobox.Chips>
      <Combobox.Portal>
        <Combobox.Positioner anchor={anchor} sideOffset={4} className="isolate z-50">
          <Combobox.Popup className="w-(--anchor-width) max-w-(--available-width) origin-(--transform-origin) overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-1 transition-[opacity,scale] duration-150 ease-out data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0 motion-reduce:transition-opacity">
            <Combobox.Empty className="px-3 py-2 text-s-400 text-muted-foreground empty:hidden">
              No persona matches.
            </Combobox.Empty>
            <Combobox.List className="max-h-64 overflow-y-auto p-1 empty:p-0">
              {(persona: Persona) => (
                <Combobox.Item
                  key={persona.id}
                  value={persona}
                  className="relative flex cursor-default items-center gap-2 rounded-md py-1.5 pr-8 pl-2.5 text-s-400 outline-hidden select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                >
                  <span className="min-w-0 flex-1 truncate">{persona.name}</span>
                  <span className="shrink-0 text-xs-400 text-muted-foreground">
                    {LANGUAGE_NAMES[persona.language]}
                  </span>
                  <Combobox.ItemIndicator className="absolute right-2 flex size-4 items-center justify-center">
                    <CheckIcon className="size-4" />
                  </Combobox.ItemIndicator>
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
