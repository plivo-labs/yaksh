import { Combobox } from "@base-ui/react/combobox";
import { CheckIcon, ChevronDownIcon, RefreshCw, SearchIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useProviderModels } from "@/lib/queries";
import { cn } from "@/lib/utils";

const SAME = "";

/** A model of the LLM provider, chosen from the list the provider gives or typed: a model the
 * list lacks, such as an Azure deployment name, can still be used. `inherit` adds a first
 * option that stands for the caller's model, given as null. */
export function ModelCombobox({
  id,
  value,
  onValueChange,
  inherit,
}: {
  id: string;
  value: string | null;
  onValueChange: (model: string | null) => void;
  inherit?: string;
}) {
  const [opened, setOpened] = useState(false);
  const [query, setQuery] = useState("");
  const models = useProviderModels(opened);
  const listed = models.data?.models ?? [];
  const typed = query.trim();
  const items = [
    ...(inherit === undefined ? [] : [SAME]),
    ...listed,
    ...(value && !listed.includes(value) ? [value] : []),
    ...(typed && !listed.includes(typed) && typed !== value ? [typed] : []),
  ];
  const label = (item: string) => (item === SAME ? `Same as the caller (${inherit})` : item);
  return (
    <Combobox.Root
      items={items}
      value={value ?? SAME}
      onValueChange={(next) => {
        if (next !== null) onValueChange(next === SAME ? null : next);
      }}
      inputValue={query}
      onInputValueChange={setQuery}
      onOpenChange={(open) => {
        if (open) setOpened(true);
        else setQuery("");
      }}
      itemToStringLabel={label}
      autoHighlight
    >
      <Combobox.Trigger
        id={id}
        className="flex h-9 w-full items-center justify-between gap-1.5 rounded-md border border-input bg-transparent px-3 text-p-400 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <span className="truncate font-mono text-s-400">{label(value ?? SAME)}</span>
        <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground" />
      </Combobox.Trigger>
      <Combobox.Portal>
        <Combobox.Positioner sideOffset={4} className="isolate z-50">
          <Combobox.Popup className="w-(--anchor-width) max-w-(--available-width) origin-(--transform-origin) overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-1 transition-[opacity,scale] duration-150 ease-out data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0 motion-reduce:transition-opacity">
            <div className="flex items-center gap-2 border-b px-3">
              <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
              <Combobox.Input
                autoFocus
                aria-label="Search models"
                placeholder="Search models"
                className="h-9 w-full bg-transparent text-s-400 outline-none placeholder:text-muted-foreground"
              />
            </div>
            <Combobox.Empty className="px-3 py-2 text-s-400 text-muted-foreground empty:hidden">
              No model matches.
            </Combobox.Empty>
            <Combobox.List className="max-h-64 overflow-y-auto p-1 empty:p-0">
              {(item: string) => (
                <Combobox.Item
                  key={item}
                  value={item}
                  className="relative flex cursor-default items-center rounded-md py-1.5 pr-8 pl-2.5 text-s-400 outline-hidden select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                >
                  <span className={cn("truncate", item !== SAME && "font-mono")}>
                    {item === typed && !listed.includes(item)
                      ? `Use “${item}” as the model name`
                      : label(item)}
                  </span>
                  <Combobox.ItemIndicator className="absolute right-2 flex size-4 items-center justify-center">
                    <CheckIcon className="size-4" />
                  </Combobox.ItemIndicator>
                </Combobox.Item>
              )}
            </Combobox.List>
            <div className="flex items-center gap-2 border-t bg-bg2 px-3 py-2">
              <span className="min-w-0 flex-1 text-xs-400 text-muted-foreground">
                {models.isFetching
                  ? "Loading the provider's models"
                  : models.isError
                    ? models.error.message
                    : `${listed.length} models from the LLM provider`}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={models.isFetching}
                onClick={() => void models.refetch()}
              >
                <RefreshCw />
                Refresh
              </Button>
            </div>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
