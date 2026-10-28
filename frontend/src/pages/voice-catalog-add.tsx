import { Play, Square } from "lucide-react";
import { useState } from "react";

import { FilterSelect } from "@/components/filter-select";
import { SearchInput } from "@/components/search-input";
import { StatusLabel } from "@/components/status-label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { FieldError } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import type { CloseGuard } from "@/hooks/use-close-guard";
import { counted } from "@/lib/format";
import { APPEAR } from "@/lib/motion";
import { type VoiceAddState, type useAddVoices, useVoiceCatalog } from "@/lib/queries";
import { defaultSettings, spokenOf } from "@/lib/speech-providers";
import type { Tone } from "@/lib/status";
import {
  LANGUAGE_NAMES,
  type Language,
  type ProviderVoice,
  type TtsModel,
  type TtsTraits,
  VOICE_GENDER_ITEMS,
  type VoiceGender,
  type VoiceInput,
  voiceGender,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { type DialogPreview, VoiceDialogBody } from "@/pages/voice-dialog-shell";
import { NAME_MAX } from "@/pages/voice-fields";

const ALL = "all";
const GENDER_FILTERS = [{ value: ALL, label: "All genders" }, ...VOICE_GENDER_ITEMS];

const catalogKey = (id: string) => `catalog:${id}`;

/** The search of the provider's own voices. */
interface Filters {
  search: string;
  language: Language | null;
  gender: VoiceGender | null;
}

const NO_FILTERS: Filters = { search: "", language: null, gender: null };

/** A voice of the last batch and where it stands. */
interface Reported {
  id: string;
  name: string;
  state: VoiceAddState;
}

const STATES: Record<VoiceAddState["status"], { tone: Tone; text: string }> = {
  waiting: { tone: "amber", text: "Waiting" },
  adding: { tone: "green", text: "Adding" },
  added: { tone: "green", text: "Added" },
  listed: { tone: "off", text: "Already listed" },
  failed: { tone: "red", text: "Not added" },
};

const NO_LANGUAGE: VoiceAddState = {
  status: "failed",
  message: "It lists no language of this model; set the language filter and add it again.",
};

/** Voices picked from the provider's own list and added at once with one model, each with its
 * name and the languages the provider lists for it. Its choices belong to one provider and model:
 * the dialog gives each pair a new form. */
export function VoiceCatalogAdd({
  traits,
  model,
  previews,
  addPicked,
  guard,
  onDirtyChange,
}: {
  traits: TtsTraits;
  /** Undefined until the account's models load, or when it has none. */
  model: TtsModel | undefined;
  previews: DialogPreview;
  /** The dialog holds the batch, because the dialog stays as it is while the batch runs. */
  addPicked: ReturnType<typeof useAddVoices>;
  guard: CloseGuard;
  /** Hears whether closing the dialog would lose picked voices. */
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  /** The voices checked in the provider's list, by ID. They stay while the list changes. */
  const [picked, setPicked] = useState<ReadonlyMap<string, ProviderVoice>>(new Map());
  const [report, setReport] = useState<Reported[]>([]);
  const adding = addPicked.isPending;

  const choose = (next: ReadonlyMap<string, ProviderVoice>) => {
    setPicked(next);
    onDirtyChange(next.size > 0);
  };

  const pick = (entry: ProviderVoice, on: boolean) => {
    const next = new Map(picked);
    if (on) next.set(entry.id, entry);
    else next.delete(entry.id);
    choose(next);
  };

  const filter = (next: Partial<Filters>) => {
    previews.stop();
    setFilters((current) => ({ ...current, ...next }));
  };

  /** Adds the picked voices with the chosen model. A voice gets the languages that the provider
   * lists for it and the model speaks; without one, the language of the filter. When every voice
   * is in the list, the dialog closes; if not, the voices not added stay picked, to add again. */
  const addAll = () => {
    if (!model) return;
    const batch = [...picked.values()].map((entry) => {
      const spoken = spokenOf(entry.listed_languages, model);
      const languages = spoken.length > 0 ? spoken : filters.language ? [filters.language] : [];
      const input: VoiceInput | null =
        languages.length > 0
          ? {
              provider: traits.provider,
              provider_voice_id: entry.id,
              model: model.id ?? undefined,
              name: [...entry.name.trim()].slice(0, NAME_MAX).join(""),
              languages,
              ...(traits.lookup
                ? {}
                : {
                    gender: entry.gender,
                    accent: entry.accent,
                    listed_languages: entry.listed_languages,
                  }),
            }
          : null;
      return { entry, input };
    });
    setReport(
      batch.map(({ entry, input }): Reported => ({
        id: entry.id,
        name: entry.name,
        state: input ? { status: "waiting" } : NO_LANGUAGE,
      })),
    );
    addPicked.mutate(
      {
        inputs: batch.flatMap(({ input }) => (input ? [input] : [])),
        onState: (id, state) =>
          setReport((current) =>
            current.map((item) => (item.id === id ? { ...item, state } : item)),
          ),
      },
      {
        onSuccess: (ended) => {
          const done = new Set(
            [...ended]
              .filter(([, state]) => state.status === "added" || state.status === "listed")
              .map(([id]) => id),
          );
          if (done.size === batch.length) guard.close();
          else choose(new Map([...picked].filter(([id]) => !done.has(id))));
        },
      },
    );
  };

  return (
    <>
      <VoiceDialogBody>
        {model && (
          <VoiceFinder
            traits={traits}
            model={model}
            filters={filters}
            onFilter={filter}
            previews={previews}
            picked={picked}
            locked={adding}
            onPick={pick}
            onClear={() => choose(new Map())}
          />
        )}
      </VoiceDialogBody>
      {report.length > 0 && <AddReport items={report} />}
      <DialogFooter className="items-center border-t px-6 py-4">
        <span className="mr-auto text-xs-400 text-muted-foreground">
          Saving speaks a test line in each voice.
        </span>
        <Button type="button" variant="ghost" disabled={adding} onClick={guard.requestClose}>
          Cancel
        </Button>
        <Button type="button" disabled={!model || picked.size === 0 || adding} onClick={addAll}>
          {adding && <Spinner />}
          {picked.size === 0 ? "Add voices" : `Add ${counted(picked.size, "voice", "voices")}`}
        </Button>
      </DialogFooter>
    </>
  );
}

/** A search of the provider's own voices: each plays in the chosen model, and any number are
 * picked. The picks stay while the search, the filters and the pages change. */
function VoiceFinder({
  traits,
  model,
  filters,
  onFilter,
  previews,
  picked,
  locked,
  onPick,
  onClear,
}: {
  traits: TtsTraits;
  model: TtsModel;
  filters: Filters;
  onFilter: (next: Partial<Filters>) => void;
  previews: DialogPreview;
  picked: ReadonlyMap<string, ProviderVoice>;
  /** The picks cannot change: the picked voices are being added. */
  locked: boolean;
  onPick: (voice: ProviderVoice, on: boolean) => void;
  onClear: () => void;
}) {
  const catalog = useVoiceCatalog({ provider: traits.provider, model: model.id, ...filters });
  const rows = (catalog.data?.pages ?? []).flatMap((page) => page.items);
  const languageItems = [
    { value: ALL, label: "All languages" },
    ...model.languages.map((language) => ({ value: language, label: LANGUAGE_NAMES[language] })),
  ];
  return (
    <div className={`grid gap-3 ${APPEAR}`}>
      <div className="flex flex-wrap gap-2">
        <SearchInput
          value={filters.search}
          onSearch={(search) => onFilter({ search })}
          label={`Search ${traits.label} voices`}
          placeholder="Search by name"
          className="min-w-48 flex-1"
        />
        <FilterSelect
          label="Filter by language"
          items={languageItems}
          value={filters.language ?? ALL}
          onChange={(value) =>
            onFilter({ language: model.languages.find((language) => language === value) ?? null })
          }
          className="w-36"
        />
        <FilterSelect
          label="Filter by gender"
          items={GENDER_FILTERS}
          value={filters.gender ?? ALL}
          onChange={(value) => onFilter({ gender: voiceGender(value) })}
          className="w-32"
        />
      </div>

      {catalog.isPending ? (
        <p className="flex items-center gap-2 text-p-400 text-muted-foreground">
          <Spinner />
          Loading voices
        </p>
      ) : catalog.isError ? (
        <FieldError>{catalog.error.message}</FieldError>
      ) : rows.length === 0 && !catalog.hasNextPage ? (
        <p className="text-p-400 text-muted-foreground">
          {filters.search || filters.language || filters.gender
            ? "No voices match."
            : "No voices found."}
        </p>
      ) : (
        <>
          <ul aria-label={`${traits.label} voices`} className="grid rounded-md border">
            {rows.map((entry) => {
              const key = catalogKey(entry.id);
              const about = [entry.gender, entry.accent].filter(Boolean).join(" · ");
              const language =
                filters.language ??
                model.languages.find((item) => entry.listed_languages.includes(item)) ??
                model.languages[0];
              const error = previews.error(key);
              return (
                <li
                  key={entry.id}
                  className="flex items-center gap-2 border-b px-3 py-2 transition-colors last:border-b-0 hover:bg-hv1"
                >
                  <label
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-3",
                      locked ? "cursor-not-allowed" : "cursor-pointer",
                    )}
                  >
                    <Checkbox
                      aria-label={`Select ${entry.name}`}
                      checked={picked.has(entry.id)}
                      disabled={locked}
                      onCheckedChange={(on) => onPick(entry, on)}
                    />
                    <span className="grid min-w-0 flex-1">
                      <span className="truncate text-p-500">{entry.name}</span>
                      {about && (
                        <span className="truncate text-s-400 text-muted-foreground capitalize">
                          {about}
                        </span>
                      )}
                      {error && <span className="text-xs-400 text-destructive">{error}</span>}
                    </span>
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={
                      previews.isPlaying(key) ? `Stop ${entry.name}` : `Play ${entry.name}`
                    }
                    aria-busy={previews.isLoading(key)}
                    onClick={() =>
                      previews.play(
                        key,
                        defaultSettings(traits.provider, entry.id, model.id),
                        language,
                      )
                    }
                  >
                    {previews.isLoading(key) ? (
                      <Spinner />
                    ) : previews.isPlaying(key) ? (
                      <Square />
                    ) : (
                      <Play />
                    )}
                  </Button>
                </li>
              );
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="text-s-400 text-muted-foreground tabular-nums">
              Showing {counted(rows.length, "voice", "voices")}
            </span>
            {picked.size > 0 && (
              <span className="flex items-center gap-1">
                <span className="text-s-500 tabular-nums">{picked.size} selected</span>
                <Button type="button" variant="ghost" size="sm" disabled={locked} onClick={onClear}>
                  Clear
                </Button>
              </span>
            )}
            {catalog.hasNextPage && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="ml-auto"
                disabled={catalog.isFetchingNextPage}
                onClick={() => void catalog.fetchNextPage()}
              >
                {catalog.isFetchingNextPage && <Spinner />}
                Load more
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** The voices of the last batch: where each one stands while they are added, and why a voice
 * was not added. */
function AddReport({ items }: { items: Reported[] }) {
  return (
    <div className="max-h-48 shrink-0 overflow-y-auto border-t px-6 py-3">
      <p role="status" className="text-s-500">
        {reportSummary(items)}
      </p>
      <ul className="mt-2 flex flex-col gap-2">
        {items.map(({ id, name, state }) => (
          <li key={id}>
            <span className="flex items-center justify-between gap-3">
              <span className="truncate text-s-400">{name}</span>
              <StatusLabel tone={STATES[state.status].tone} live={state.status === "adding"}>
                {STATES[state.status].text}
              </StatusLabel>
            </span>
            {state.status === "failed" && (
              <p className="mt-0.5 text-xs-400 text-destructive">{state.message}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "Adding 5 voices: 2 done" while they are added; then how many ended each way. */
function reportSummary(items: Reported[]): string {
  const count = (status: VoiceAddState["status"]) =>
    items.filter((item) => item.state.status === status).length;
  const open = count("waiting") + count("adding");
  if (open > 0) {
    return `Adding ${counted(items.length, "voice", "voices")}: ${items.length - open} done`;
  }
  const ends: [number, string][] = [
    [count("added"), "added"],
    [count("listed"), "already listed"],
    [count("failed"), "not added"],
  ];
  return ends
    .filter(([amount]) => amount > 0)
    .map(([amount, text]) => `${amount} ${text}`)
    .join(", ");
}
