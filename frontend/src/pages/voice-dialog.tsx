import { Play, Square } from "lucide-react";
import { type KeyboardEvent, type SubmitEvent, useRef, useState } from "react";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { FilterSelect } from "@/components/filter-select";
import { GenderBadge } from "@/components/gender-badge";
import { Fact } from "@/components/panel";
import { SearchInput } from "@/components/search-input";
import { Segmented } from "@/components/segmented";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useCloseGuard } from "@/hooks/use-close-guard";
import type { VoicePreview } from "@/hooks/use-voice-preview";
import { counted } from "@/lib/format";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import {
  useAddVoice,
  useDeleteVoice,
  useEditVoice,
  useLookupVoice,
  useSettings,
  useVoiceCatalog,
} from "@/lib/queries";
import {
  TTS_PROVIDERS,
  defaultSettings,
  hasCredential,
  ttsModel,
  ttsTraits,
} from "@/lib/speech-providers";
import {
  LANGUAGE_NAMES,
  type Language,
  type ProviderVoice,
  type TtsModel,
  type TtsTraits,
  type Voice,
  type VoiceGender,
  type VoiceProvider,
  type VoiceSettings,
  type VoiceSource,
} from "@/lib/types";

const ALL = "all";
const GENDER_ITEMS: { value: VoiceGender; label: string }[] = [
  { value: "female", label: "Female" },
  { value: "male", label: "Male" },
  { value: "neutral", label: "Neutral" },
];
const GENDERS: { value: VoiceGender | "unset"; label: string }[] = [
  { value: "unset", label: "Not set" },
  ...GENDER_ITEMS,
];
const GENDER_FILTERS = [{ value: ALL, label: "All genders" }, ...GENDER_ITEMS];

type Mode = "find" | "id";
const MODES: { value: Mode; label: string }[] = [
  { value: "find", label: "Find a voice" },
  { value: "id", label: "Enter an ID" },
];
const SOURCES: { value: VoiceSource; label: string }[] = [
  { value: "account", label: "Account" },
  { value: "library", label: "Library" },
];

const previewKey = (language: Language) => `voice:${language}`;
const catalogKey = (id: string) => `catalog:${id}`;

const genderOf = (value: string): VoiceGender | null =>
  value === "female" || value === "male" || value === "neutral" ? value : null;

interface Draft {
  name: string;
  languages: Language[];
  /** Entered by hand for a voice that the provider does not describe. */
  gender: VoiceGender | null;
  accent: string;
}

interface Details {
  providerVoiceId: string;
  gender: ProviderVoice["gender"];
  accent: string | null;
  listed: Language[];
}

/** The search of the provider's own voices. */
interface Filters {
  source: VoiceSource;
  search: string;
  language: Language | null;
  gender: VoiceGender | null;
}

const NO_FILTERS: Filters = { source: "account", search: "", language: null, gender: null };

/** A voice picked from the provider's voices, with the list it came from. */
interface Picked {
  voice: ProviderVoice;
  source: VoiceSource;
}

function joined(names: string[]): string {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

/** Add a voice of any text-to-speech provider with a key, or edit one in the list. A new voice
 * gets one of its provider's models, and is picked from the provider's voices or entered by its
 * ID. A provider with lookup fills the details from the ID; for the others they are entered by
 * hand. The server speaks a line in the voice and model before it saves it. */
export function VoiceDialog({
  voice,
  providers,
  preview,
  onClosed,
}: {
  voice?: Voice;
  /** The server's list of text-to-speech providers. */
  providers: TtsTraits[];
  preview: VoicePreview;
  onClosed: () => void;
}) {
  const add = useAddVoice();
  const edit = useEditVoice();
  const remove = useDeleteVoice();
  const lookup = useLookupVoice();
  const settings = useSettings();
  const save = voice ? edit : add;

  const [provider, setProvider] = useState<VoiceProvider>(
    () =>
      voice?.provider ??
      TTS_PROVIDERS.find((item) => hasCredential(item, settings.data?.secrets))?.value ??
      "elevenlabs",
  );
  const traits = ttsTraits(providers, provider);
  const [modelId, setModelId] = useState(() => (voice ? voice.model : traits.models[0].id));
  const model = ttsModel(traits, modelId) ?? traits.models[0];
  const [mode, setMode] = useState<Mode>("find");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [typedId, setTypedId] = useState("");
  const [found, setFound] = useState<Details | null>(null);
  const [initial] = useState<Draft>(() => ({
    name: voice?.name ?? "",
    languages: voice?.languages ?? [],
    gender: null,
    accent: "",
  }));
  const [draft, setDraft] = useState<Draft>(initial);
  const [submitted, setSubmitted] = useState(false);
  /** The previews this dialog started, so that closing it or changing the voice stops them. */
  const played = useRef(new Set<string>());

  const details: Details | null = voice
    ? {
        providerVoiceId: voice.provider_voice_id,
        gender: voice.gender,
        accent: voice.accent,
        listed: voice.listed_languages,
      }
    : mode === "find"
      ? picked && {
          providerVoiceId: picked.voice.id,
          gender: picked.voice.gender,
          accent: picked.voice.accent,
          listed: picked.voice.listed_languages,
        }
      : traits.lookup
        ? found && found.providerVoiceId === typedId.trim()
          ? found
          : null
        : typedId.trim()
          ? {
              providerVoiceId: typedId.trim(),
              gender: draft.gender,
              accent: draft.accent.trim() || null,
              listed: [],
            }
          : null;
  /** The person enters the gender and accent: no lookup or list describes the voice. */
  const entered = !voice && mode === "id" && !traits.lookup;
  /** `details.listed` holds what the provider lists for the voice. */
  const listedKnown = voice
    ? traits.lookup || voice.listed_languages.length > 0
    : mode === "find" || traits.lookup;
  const dirty = voice
    ? JSON.stringify(draft) !== JSON.stringify(initial)
    : picked !== null || typedId.trim() !== "";
  const guard = useCloseGuard(dirty);

  const change = (next: (current: Draft) => Partial<Draft>) => {
    save.reset();
    setDraft((current) => ({ ...current, ...next(current) }));
  };

  /** The languages of `listed` that the model speaks. */
  const spokenOf = (listed: Language[], speaker: TtsModel = model) =>
    speaker.languages.filter((language) => listed.includes(language));

  const toggleLanguage = (language: Language, on: boolean) =>
    change((current) => ({
      languages: model.languages.filter((item) =>
        item === language ? on : current.languages.includes(item),
      ),
    }));

  const togglePreview = (key: string, spoken: VoiceSettings, language: Language) => {
    played.current.add(key);
    preview.toggle(key, spoken, language);
  };

  const stopPreviews = () => {
    for (const key of played.current) preview.reset(key);
  };

  const changeId = (value: string) => {
    lookup.reset();
    add.reset();
    stopPreviews();
    setTypedId(value);
  };

  const getDetails = () => {
    const providerVoiceId = typedId.trim();
    if (!providerVoiceId || details) return;
    lookup.mutate(
      { provider, id: providerVoiceId },
      {
        onSuccess: (answer) => {
          setFound({
            providerVoiceId,
            gender: answer.gender,
            accent: answer.accent,
            listed: answer.listed_languages,
          });
          change(() => ({ name: answer.name, languages: spokenOf(answer.listed_languages) }));
        },
      },
    );
  };

  const onIdKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    getDetails();
  };

  const filter = (next: Partial<Filters>) => {
    stopPreviews();
    setFilters((current) => ({ ...current, ...next }));
  };

  const pick = (entry: ProviderVoice) => {
    stopPreviews();
    setPicked({ voice: entry, source: filters.source });
    change(() => ({ name: entry.name, languages: spokenOf(entry.listed_languages) }));
  };

  const unpick = () => {
    stopPreviews();
    add.reset();
    setPicked(null);
  };

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!details) return;
    const name = draft.name.trim();
    const valid = Boolean(name) && draft.languages.length > 0;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    const body = { name, languages: draft.languages };
    if (voice) {
      edit.mutate({ id: voice.id, ...body }, { onSuccess: guard.close });
      return;
    }
    const source = picked?.source ?? "account";
    add.mutate(
      {
        ...body,
        provider,
        provider_voice_id: details.providerVoiceId,
        model: modelId,
        source,
        ...(traits.lookup && source === "account"
          ? {}
          : { gender: details.gender, accent: details.accent, listed_languages: details.listed }),
      },
      { onSuccess: guard.close },
    );
  };

  const chooseProvider = (next: VoiceProvider) => {
    const first = ttsTraits(providers, next).models[0];
    changeId("");
    setFound(null);
    setPicked(null);
    setFilters(NO_FILTERS);
    setProvider(next);
    setModelId(first.id);
    change((current) => ({ languages: spokenOf(current.languages, first) }));
  };

  const chooseModel = (next: string) => {
    const chosen = ttsModel(traits, next);
    if (!chosen) return;
    stopPreviews();
    setModelId(chosen.id);
    setFilters((current) =>
      current.language && !chosen.languages.includes(current.language)
        ? { ...current, language: null }
        : current,
    );
    change((current) => ({ languages: spokenOf(current.languages, chosen) }));
  };

  /** Each way to find the voice starts over. */
  const chooseMode = (next: Mode) => {
    if (next === mode) return;
    changeId("");
    setFound(null);
    setPicked(null);
    setDraft(initial);
    setSubmitted(false);
    setMode(next);
  };

  const spoken = details ? defaultSettings(provider, details.providerVoiceId, modelId) : null;
  const previewError = model.languages
    .map((language) => preview.error(previewKey(language)))
    .find(Boolean);
  const unlisted =
    details && listedKnown
      ? draft.languages.filter((language) => !details.listed.includes(language))
      : [];

  return (
    <Dialog
      open={guard.open}
      onOpenChange={(next) => !next && guard.requestClose()}
      onOpenChangeComplete={(next) => {
        if (next) return;
        stopPreviews();
        onClosed();
      }}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>{voice ? "Edit voice" : "Add voice"}</DialogTitle>
        </DialogHeader>

        <form
          id="voice-form"
          noValidate
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 py-1"
        >
          <FieldGroup className="pb-6">
            {voice ? null : (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="voice-provider">Provider</FieldLabel>
                    <Select
                      items={TTS_PROVIDERS.map((item) => ({
                        value: item.value,
                        label: item.label,
                      }))}
                      value={provider}
                      onValueChange={(next) => next && chooseProvider(next)}
                    >
                      <SelectTrigger id="voice-provider" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TTS_PROVIDERS.map((item) => (
                          <SelectItem
                            key={item.value}
                            value={item.value}
                            disabled={!hasCredential(item, settings.data?.secrets)}
                          >
                            {item.label}
                            {!hasCredential(item, settings.data?.secrets) && " (no key)"}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {!traits.word_timestamps && (
                      <FieldDescription className="text-warning-foreground">
                        Sentence timing: a cut-off reply shows whole sentences, not words.
                      </FieldDescription>
                    )}
                  </Field>
                  {model.id !== null && (
                    <Field>
                      <FieldLabel htmlFor="voice-model">Model</FieldLabel>
                      <Select
                        items={traits.models.map((item) => ({ value: item.id, label: item.label }))}
                        value={model.id}
                        onValueChange={(next) => next && chooseModel(next)}
                      >
                        <SelectTrigger id="voice-model" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {traits.models.map((item) => (
                            <SelectItem key={item.id} value={item.id}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {model.speed_min === model.speed_max && (
                        <FieldDescription>This model takes no speed setting.</FieldDescription>
                      )}
                    </Field>
                  )}
                </div>

                <div className="grid gap-4">
                  <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
                    <Segmented label="Voice" value={mode} options={MODES} onChange={chooseMode} />
                    {mode === "find" && !picked && traits.library && (
                      <Segmented
                        label="Source"
                        value={filters.source}
                        options={SOURCES}
                        onChange={(source) => filter({ source })}
                      />
                    )}
                  </div>
                  {mode === "id" ? (
                    <Field>
                      <FieldLabel htmlFor="provider-voice-id">{traits.label} voice ID</FieldLabel>
                      <div className="flex gap-2">
                        <Input
                          id="provider-voice-id"
                          autoFocus
                          autoComplete="off"
                          spellCheck={false}
                          className="font-mono"
                          value={typedId}
                          onChange={(e) => changeId(e.target.value)}
                          onKeyDown={onIdKey}
                        />
                        {traits.lookup && (
                          <Button
                            type="button"
                            variant="outline"
                            disabled={!typedId.trim() || details !== null || lookup.isPending}
                            onClick={getDetails}
                          >
                            {lookup.isPending && <Spinner />}
                            Get details
                          </Button>
                        )}
                      </div>
                      {!traits.lookup && (
                        <FieldDescription>
                          {traits.label} has no voice lookup. Enter the details below.
                        </FieldDescription>
                      )}
                      {lookup.error && <FieldError>{lookup.error.message}</FieldError>}
                    </Field>
                  ) : picked ? (
                    <div
                      className={`flex items-center gap-3 rounded-md border px-3 py-2 ${APPEAR}`}
                    >
                      <span className="grid min-w-0 flex-1">
                        <span className="truncate text-p-500">{picked.voice.name}</span>
                        <span className="truncate font-mono text-xs-400 text-muted-foreground">
                          {picked.voice.id}
                        </span>
                      </span>
                      {picked.source === "library" && <Badge>Library</Badge>}
                      <Button type="button" variant="outline" size="sm" onClick={unpick}>
                        Change
                      </Button>
                    </div>
                  ) : (
                    <VoiceFinder
                      traits={traits}
                      model={model}
                      filters={filters}
                      onFilter={filter}
                      preview={preview}
                      onPlay={togglePreview}
                      onPick={pick}
                    />
                  )}
                </div>
              </>
            )}

            {details && (
              <>
                {entered ? (
                  <div className={`grid grid-cols-2 gap-4 ${APPEAR}`}>
                    <Field>
                      <FieldLabel htmlFor="voice-gender">Gender</FieldLabel>
                      <Select
                        items={GENDERS}
                        value={draft.gender ?? "unset"}
                        onValueChange={(next) => next && change(() => ({ gender: genderOf(next) }))}
                      >
                        <SelectTrigger id="voice-gender">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {GENDERS.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field>
                      <FieldLabel htmlFor="voice-accent">Accent</FieldLabel>
                      <Input
                        id="voice-accent"
                        maxLength={80}
                        value={draft.accent}
                        onChange={(e) => change(() => ({ accent: e.target.value }))}
                      />
                    </Field>
                  </div>
                ) : (
                  <div className={`flex flex-wrap items-center gap-2 text-p-400 ${APPEAR}`}>
                    {details.gender && <GenderBadge gender={details.gender} />}
                    {details.accent && (
                      <span className="text-muted-foreground capitalize">{details.accent}</span>
                    )}
                  </div>
                )}
                {voice && (
                  <dl className="flex flex-wrap gap-x-10 gap-y-3">
                    <Fact label="Voice id">
                      <CopyId id={voice.id} label="voice id" />
                    </Fact>
                    <Fact label={`${traits.label} voice ID`}>
                      <CopyId
                        id={voice.provider_voice_id}
                        label={`${traits.label} voice ID`}
                        full
                      />
                    </Fact>
                    {voice.model !== null && (
                      <Fact label="Model">
                        {ttsModel(traits, voice.model)?.label ?? voice.model}
                      </Fact>
                    )}
                  </dl>
                )}

                <Field className={APPEAR}>
                  <FieldLabel htmlFor="voice-name">Name</FieldLabel>
                  <Input
                    id="voice-name"
                    required
                    maxLength={80}
                    aria-invalid={submitted && !draft.name.trim()}
                    value={draft.name}
                    onChange={(e) => change(() => ({ name: e.target.value }))}
                  />
                  {submitted && !draft.name.trim() && <FieldError>Enter a name.</FieldError>}
                </Field>

                <FieldSet className={APPEAR}>
                  <FieldLegend variant="label">Languages</FieldLegend>
                  <ul className="grid gap-1">
                    {model.languages.map((language) => {
                      const key = previewKey(language);
                      return (
                        <li key={language} className="flex items-center gap-3">
                          <Checkbox
                            id={`language-${language}`}
                            checked={draft.languages.includes(language)}
                            onCheckedChange={(on) => toggleLanguage(language, on)}
                          />
                          <label htmlFor={`language-${language}`} className="flex-1 text-p-400">
                            {LANGUAGE_NAMES[language]}
                          </label>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={
                              preview.isPlaying(key)
                                ? `Stop ${LANGUAGE_NAMES[language]} preview`
                                : `Play ${LANGUAGE_NAMES[language]} preview`
                            }
                            aria-busy={preview.isLoading(key)}
                            onClick={() => spoken && togglePreview(key, spoken, language)}
                          >
                            {preview.isLoading(key) ? (
                              <Spinner />
                            ) : preview.isPlaying(key) ? (
                              <Square />
                            ) : (
                              <Play />
                            )}
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                  {unlisted.length > 0 && (
                    <FieldDescription className={APPEAR}>
                      {traits.label} does not list {joined(unlisted.map((l) => LANGUAGE_NAMES[l]))}{" "}
                      for this voice. Play the preview before you use it.
                    </FieldDescription>
                  )}
                  {submitted && draft.languages.length === 0 && (
                    <FieldError>Choose at least one language.</FieldError>
                  )}
                  {previewError && <FieldError>{previewError}</FieldError>}
                </FieldSet>
              </>
            )}
          </FieldGroup>
        </form>

        {(save.error || remove.error) && (
          <FieldError className="px-6 pb-3">{(save.error ?? remove.error)?.message}</FieldError>
        )}

        <DialogFooter className="items-center border-t px-6 py-4">
          {!voice && (
            <span className="mr-auto text-xs-400 text-muted-foreground">
              Saving speaks a test line in this voice.
            </span>
          )}
          {voice && (
            <DeleteConfirm
              name={initial.name}
              description="Personas that use this voice keep it."
              pending={remove.isPending}
              onDelete={(close) =>
                remove.mutate(voice.id, { onSuccess: guard.close, onSettled: close })
              }
            />
          )}
          <Button type="button" variant="ghost" onClick={guard.requestClose}>
            Cancel
          </Button>
          <Button type="submit" form="voice-form" disabled={!details || save.isPending}>
            {save.isPending && <Spinner />}
            {voice ? "Save changes" : "Add voice"}
          </Button>
        </DialogFooter>

        <DiscardConfirm subject="voice" {...guard.discard} />
      </DialogContent>
    </Dialog>
  );
}

/** A search of the provider's own voices: each plays in the chosen model, and one is picked. */
function VoiceFinder({
  traits,
  model,
  filters,
  onFilter,
  preview,
  onPlay,
  onPick,
}: {
  traits: TtsTraits;
  model: TtsModel;
  filters: Filters;
  onFilter: (next: Partial<Filters>) => void;
  preview: VoicePreview;
  onPlay: (key: string, voice: VoiceSettings, language: Language) => void;
  onPick: (voice: ProviderVoice) => void;
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
          onChange={(value) => onFilter({ gender: genderOf(value) })}
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
              const error = preview.error(key);
              return (
                <li
                  key={entry.id}
                  className="flex items-center gap-2 border-b px-3 py-2 last:border-b-0"
                >
                  <span className="grid min-w-0 flex-1">
                    <span className="truncate text-p-500">{entry.name}</span>
                    {about && (
                      <span className="truncate text-s-400 text-muted-foreground capitalize">
                        {about}
                      </span>
                    )}
                    {error && <span className="text-xs-400 text-destructive">{error}</span>}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={
                      preview.isPlaying(key) ? `Stop ${entry.name}` : `Play ${entry.name}`
                    }
                    aria-busy={preview.isLoading(key)}
                    onClick={() =>
                      onPlay(key, defaultSettings(traits.provider, entry.id, model.id), language)
                    }
                  >
                    {preview.isLoading(key) ? (
                      <Spinner />
                    ) : preview.isPlaying(key) ? (
                      <Square />
                    ) : (
                      <Play />
                    )}
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => onPick(entry)}>
                    Pick
                  </Button>
                </li>
              );
            })}
          </ul>
          <div className="flex items-center justify-between gap-3">
            <span className="text-s-400 text-muted-foreground tabular-nums">
              Showing {counted(rows.length, "voice", "voices")}
            </span>
            {catalog.hasNextPage && (
              <Button
                type="button"
                variant="outline"
                size="sm"
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
