import { Play, Square } from "lucide-react";
import { type KeyboardEvent, type SubmitEvent, useRef, useState } from "react";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { FilterSelect } from "@/components/filter-select";
import { GenderBadge } from "@/components/gender-badge";
import { Fact } from "@/components/panel";
import { SearchInput } from "@/components/search-input";
import { Segmented } from "@/components/segmented";
import { StatusLabel } from "@/components/status-label";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCloseGuard } from "@/hooks/use-close-guard";
import type { VoicePreview } from "@/hooks/use-voice-preview";
import { counted } from "@/lib/format";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import {
  type VoiceAddState,
  useAddVoice,
  useAddVoices,
  useDeleteVoice,
  useEditVoice,
  useLookupVoice,
  useSettings,
  useVoiceCatalog,
} from "@/lib/queries";
import {
  CUTS_AT_SENTENCES,
  TTS_PROVIDERS,
  defaultSettings,
  hasCredential,
  ttsModel,
  ttsTraits,
} from "@/lib/speech-providers";
import type { Tone } from "@/lib/status";
import {
  LANGUAGE_NAMES,
  type Language,
  type ProviderVoice,
  type TtsModel,
  type TtsTraits,
  type Voice,
  type VoiceGender,
  type VoiceInput,
  type VoiceProvider,
  type VoiceSettings,
  type VoiceSource,
} from "@/lib/types";
import { cn } from "@/lib/utils";

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
const LIBRARY_HINT =
  "Library: ElevenLabs' public voices. The account's plan must allow library voices; Yaksh adds a voice only after it speaks a line.";

/** The longest name the server takes, in code points. */
const NAME_MAX = 80;

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

function joined(names: string[]): string {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

/** What sets a model apart from the provider's other models: its speeds and its languages. */
function modelHint(model: TtsModel): string {
  const speed =
    model.speed_min === model.speed_max
      ? "No speed setting."
      : `Speed ${model.speed_min.toFixed(2)} to ${model.speed_max.toFixed(2)}.`;
  return `${speed} Speaks ${joined(model.languages.map((language) => LANGUAGE_NAMES[language]))}.`;
}

/** Add voices of any text-to-speech provider with a key, or edit one in the list. A new voice
 * gets one of its provider's models. Several are picked from the provider's voices and added
 * at once, each with its name and the languages the provider lists for it; or one is entered by
 * its ID. A provider with lookup fills the details from the ID; for the others they are entered
 * by hand. The server speaks a line in each voice and model before it saves it. */
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
  const addPicked = useAddVoices();
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
  /** The voices checked in the provider's list, by ID. They stay while the list changes. */
  const [picked, setPicked] = useState<ReadonlyMap<string, Picked>>(new Map());
  const [report, setReport] = useState<Reported[]>([]);
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
  /** While the picked voices are added, the choices that made the batch stay as they are. */
  const adding = addPicked.isPending;

  const details: Details | null = voice
    ? {
        providerVoiceId: voice.provider_voice_id,
        gender: voice.gender,
        accent: voice.accent,
        listed: voice.listed_languages,
      }
    : mode === "find"
      ? null
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
  const listedKnown = voice ? traits.lookup || voice.listed_languages.length > 0 : traits.lookup;
  const dirty = voice
    ? JSON.stringify(draft) !== JSON.stringify(initial)
    : picked.size > 0 || typedId.trim() !== "";
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

  const pick = (entry: ProviderVoice, on: boolean) =>
    setPicked((current) => {
      const next = new Map(current);
      if (on) next.set(entry.id, { voice: entry, source: filters.source });
      else next.delete(entry.id);
      return next;
    });

  /** Adds the picked voices with the chosen model. A voice gets the languages that the provider
   * lists for it and the model speaks; without one, the language of the filter. When every voice
   * is in the list, the dialog closes; if not, the voices not added stay picked, to add again. */
  const addAll = () => {
    const batch = [...picked.values()].map(({ voice: entry, source }) => {
      const spoken = spokenOf(entry.listed_languages);
      const languages = spoken.length > 0 ? spoken : filters.language ? [filters.language] : [];
      const input: VoiceInput | null =
        languages.length > 0
          ? {
              provider,
              provider_voice_id: entry.id,
              model: model.id ?? undefined,
              name: [...entry.name.trim()].slice(0, NAME_MAX).join(""),
              languages,
              source,
              ...(traits.lookup && source === "account"
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
          else setPicked((current) => new Map([...current].filter(([id]) => !done.has(id))));
        },
      },
    );
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
    add.mutate(
      {
        ...body,
        provider,
        provider_voice_id: details.providerVoiceId,
        model: modelId,
        ...(traits.lookup
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
    setPicked(new Map());
    setReport([]);
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
    setPicked(new Map());
    setReport([]);
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
      onOpenChange={(next) => !next && !adding && guard.requestClose()}
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
                      disabled={adding}
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
                        {CUTS_AT_SENTENCES.tip}
                      </FieldDescription>
                    )}
                  </Field>
                  {model.id !== null && (
                    <Field>
                      <FieldLabel htmlFor="voice-model">Model</FieldLabel>
                      <Select
                        items={traits.models.map((item) => ({ value: item.id, label: item.label }))}
                        value={model.id}
                        disabled={adding}
                        onValueChange={(next) => next && chooseModel(next)}
                      >
                        <SelectTrigger id="voice-model" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {traits.models.map((item) => (
                            <Tooltip key={item.id}>
                              <TooltipTrigger render={<SelectItem value={item.id} />}>
                                {item.label}
                              </TooltipTrigger>
                              <TooltipContent side="right" className="max-w-72">
                                {modelHint(item)}
                              </TooltipContent>
                            </Tooltip>
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
                    <Segmented
                      label="Voice"
                      value={mode}
                      options={MODES}
                      disabled={adding}
                      onChange={chooseMode}
                    />
                    {mode === "find" && traits.library && (
                      <Segmented
                        label="Source"
                        hint={LIBRARY_HINT}
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
                  ) : (
                    <VoiceFinder
                      traits={traits}
                      model={model}
                      filters={filters}
                      onFilter={filter}
                      preview={preview}
                      onPlay={togglePreview}
                      picked={picked}
                      locked={adding}
                      onPick={pick}
                      onClear={() => setPicked(new Map())}
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
                    maxLength={NAME_MAX}
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

        {report.length > 0 && <AddReport items={report} />}

        {(save.error || remove.error) && (
          <FieldError className="px-6 pb-3">{(save.error ?? remove.error)?.message}</FieldError>
        )}

        <DialogFooter className="items-center border-t px-6 py-4">
          {!voice && (
            <span className="mr-auto text-xs-400 text-muted-foreground">
              Saving speaks a test line in {mode === "find" ? "each" : "this"} voice.
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
          <Button type="button" variant="ghost" disabled={adding} onClick={guard.requestClose}>
            Cancel
          </Button>
          {!voice && mode === "find" ? (
            <Button type="button" disabled={picked.size === 0 || adding} onClick={addAll}>
              {adding && <Spinner />}
              {picked.size === 0 ? "Add voices" : `Add ${counted(picked.size, "voice", "voices")}`}
            </Button>
          ) : (
            <Button type="submit" form="voice-form" disabled={!details || save.isPending}>
              {save.isPending && <Spinner />}
              {voice ? "Save changes" : "Add voice"}
            </Button>
          )}
        </DialogFooter>

        <DiscardConfirm subject="voice" {...guard.discard} />
      </DialogContent>
    </Dialog>
  );
}

/** A search of the provider's own voices: each plays in the chosen model, and any number are
 * picked. The picks stay while the search, the filters and the pages change. */
function VoiceFinder({
  traits,
  model,
  filters,
  onFilter,
  preview,
  onPlay,
  picked,
  locked,
  onPick,
  onClear,
}: {
  traits: TtsTraits;
  model: TtsModel;
  filters: Filters;
  onFilter: (next: Partial<Filters>) => void;
  preview: VoicePreview;
  onPlay: (key: string, voice: VoiceSettings, language: Language) => void;
  picked: ReadonlyMap<string, Picked>;
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
