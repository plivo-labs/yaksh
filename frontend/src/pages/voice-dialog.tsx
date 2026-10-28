import { Play, Square } from "lucide-react";
import { type KeyboardEvent, type SubmitEvent, useState } from "react";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { GenderBadge } from "@/components/gender-badge";
import { Fact } from "@/components/panel";
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
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import {
  useAddVoice,
  useDeleteVoice,
  useEditVoice,
  useLookupVoice,
  useSettings,
} from "@/lib/queries";
import { TTS_PROVIDERS, TTS_UNSPOKEN, hasCredential, ttsProvider } from "@/lib/speech-providers";
import {
  LANGUAGE_NAMES,
  type Language,
  type ProviderVoice,
  type Voice,
  type VoiceGender,
  type VoiceProvider,
  type VoiceSettings,
} from "@/lib/types";

const LANGUAGES = Object.keys(LANGUAGE_NAMES) as Language[];
const GENDERS: { value: VoiceGender | "unset"; label: string }[] = [
  { value: "unset", label: "Not set" },
  { value: "female", label: "Female" },
  { value: "male", label: "Male" },
  { value: "neutral", label: "Neutral" },
];

const previewKey = (language: Language) => `voice:${language}`;

const genderOf = (value: string): VoiceGender | null =>
  value === "female" || value === "male" || value === "neutral" ? value : null;

interface Draft {
  name: string;
  languages: Language[];
  /** Entered by hand for a provider without lookup. */
  gender: VoiceGender | null;
  accent: string;
}

interface Details {
  providerVoiceId: string;
  gender: ProviderVoice["gender"];
  accent: string | null;
  listed: Language[];
}

function joined(names: string[]): string {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

/** Add a voice of any text-to-speech provider with a key, or edit one in the list. A provider
 * with lookup fills the details from the voice's ID; for the others they are entered by hand,
 * and the server speaks a line in the voice before it saves it. */
export function VoiceDialog({
  voice,
  preview,
  onClosed,
}: {
  voice?: Voice;
  preview: VoicePreview;
  onClosed: () => void;
}) {
  const add = useAddVoice();
  const edit = useEditVoice();
  const remove = useDeleteVoice();
  const lookup = useLookupVoice();
  const settings = useSettings();
  const save = voice ? edit : add;

  const [provider, setProvider] = useState<VoiceProvider>(voice?.provider ?? "elevenlabs");
  const traits = ttsProvider(provider);
  const unspoken = TTS_UNSPOKEN[provider] ?? [];
  const languages = LANGUAGES.filter((language) => !unspoken.includes(language));
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

  const details: Details | null = voice
    ? {
        providerVoiceId: voice.provider_voice_id,
        gender: voice.gender,
        accent: voice.accent,
        listed: voice.listed_languages,
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
  const dirty = voice ? JSON.stringify(draft) !== JSON.stringify(initial) : typedId.trim() !== "";
  const guard = useCloseGuard(dirty);

  const change = (next: (current: Draft) => Partial<Draft>) => {
    save.reset();
    setDraft((current) => ({ ...current, ...next(current) }));
  };

  const toggleLanguage = (language: Language, on: boolean) =>
    change((current) => ({
      languages: languages.filter((item) =>
        item === language ? on : current.languages.includes(item),
      ),
    }));

  const stopPreviews = () => {
    for (const language of LANGUAGES) preview.reset(previewKey(language));
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
          change(() => ({ name: answer.name, languages: answer.listed_languages }));
        },
      },
    );
  };

  const onIdKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    getDetails();
  };

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!details) return;
    const name = draft.name.trim();
    const valid = Boolean(name) && draft.languages.length > 0;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    const body = { name, languages: draft.languages };
    if (voice) edit.mutate({ id: voice.id, ...body }, { onSuccess: guard.close });
    else
      add.mutate(
        {
          ...body,
          provider,
          provider_voice_id: details.providerVoiceId,
          ...(traits.lookup ? {} : { gender: draft.gender, accent: draft.accent.trim() || null }),
        },
        { onSuccess: guard.close },
      );
  };

  const chooseProvider = (next: VoiceProvider) => {
    changeId("");
    setFound(null);
    setProvider(next);
    change((current) => ({
      languages: current.languages.filter((language) => !TTS_UNSPOKEN[next]?.includes(language)),
    }));
  };

  const spoken: VoiceSettings | null = details
    ? {
        provider,
        id: details.providerVoiceId,
        speed: 1,
        stability: provider === "elevenlabs" ? 0.5 : null,
      }
    : null;
  const previewError = LANGUAGES.map((language) => preview.error(previewKey(language))).find(
    Boolean,
  );
  const unlisted =
    details && traits.lookup
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
                <Field>
                  <FieldLabel htmlFor="voice-provider">Provider</FieldLabel>
                  <Select
                    items={TTS_PROVIDERS.map((item) => ({ value: item.value, label: item.label }))}
                    value={provider}
                    onValueChange={(next) => next && chooseProvider(next)}
                  >
                    <SelectTrigger id="voice-provider" className="w-60">
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
                  {!traits.wordTimestamps && (
                    <FieldDescription className="text-warning-foreground">
                      Sentence timing: a cut-off reply shows whole sentences, not words.
                    </FieldDescription>
                  )}
                </Field>
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
              </>
            )}

            {details && (
              <>
                {voice || traits.lookup ? (
                  <div className={`flex flex-wrap items-center gap-2 text-p-400 ${APPEAR}`}>
                    {details.gender && <GenderBadge gender={details.gender} />}
                    {details.accent && (
                      <span className="text-muted-foreground capitalize">{details.accent}</span>
                    )}
                  </div>
                ) : (
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
                    {languages.map((language) => {
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
                            onClick={() => spoken && preview.toggle(key, spoken, language)}
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
          {!voice && !traits.lookup && (
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
