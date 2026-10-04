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
import { Spinner } from "@/components/ui/spinner";
import { useCloseGuard } from "@/hooks/use-close-guard";
import type { VoicePreview } from "@/hooks/use-voice-preview";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import { useAddVoice, useDeleteVoice, useEditVoice, useLookupVoice } from "@/lib/queries";
import {
  LANGUAGE_NAMES,
  type Language,
  type ProviderVoice,
  type Voice,
  type VoiceSettings,
} from "@/lib/types";

const LANGUAGES = Object.keys(LANGUAGE_NAMES) as Language[];

const previewKey = (language: Language) => `voice:${language}`;

interface Draft {
  name: string;
  languages: Language[];
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

/** Add a voice by its ElevenLabs ID, or edit one in the list. */
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
  const save = voice ? edit : add;

  const [typedId, setTypedId] = useState("");
  const [found, setFound] = useState<Details | null>(null);
  const [initial] = useState<Draft>(() => ({
    name: voice?.name ?? "",
    languages: voice?.languages ?? [],
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
    : found && found.providerVoiceId === typedId.trim()
      ? found
      : null;
  const dirty = voice ? JSON.stringify(draft) !== JSON.stringify(initial) : typedId.trim() !== "";
  const guard = useCloseGuard(dirty);

  const change = (next: (current: Draft) => Partial<Draft>) => {
    save.reset();
    setDraft((current) => ({ ...current, ...next(current) }));
  };

  const toggleLanguage = (language: Language, on: boolean) =>
    change((current) => ({
      languages: LANGUAGES.filter((item) =>
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
    lookup.mutate(providerVoiceId, {
      onSuccess: (answer) => {
        setFound({
          providerVoiceId,
          gender: answer.gender,
          accent: answer.accent,
          listed: answer.listed_languages,
        });
        change(() => ({ name: answer.name, languages: answer.listed_languages }));
      },
    });
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
        { ...body, provider: "elevenlabs", provider_voice_id: details.providerVoiceId },
        { onSuccess: guard.close },
      );
  };

  const settings: VoiceSettings | null = details
    ? { provider: "elevenlabs", id: details.providerVoiceId, speed: 1, stability: 0.5 }
    : null;
  const previewError = LANGUAGES.map((language) => preview.error(previewKey(language))).find(
    Boolean,
  );
  const unlisted = details
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
              <Field>
                <FieldLabel htmlFor="provider-voice-id">ElevenLabs voice ID</FieldLabel>
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
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!typedId.trim() || details !== null || lookup.isPending}
                    onClick={getDetails}
                  >
                    {lookup.isPending && <Spinner />}
                    Get details
                  </Button>
                </div>
                {lookup.error && <FieldError>{lookup.error.message}</FieldError>}
              </Field>
            )}

            {details && (
              <>
                <div className={`flex flex-wrap items-center gap-2 text-sm ${APPEAR}`}>
                  {details.gender && <GenderBadge gender={details.gender} />}
                  {details.accent && (
                    <span className="text-muted-foreground capitalize">{details.accent}</span>
                  )}
                </div>
                {voice && (
                  <dl className="flex flex-wrap gap-x-10 gap-y-3">
                    <Fact label="Voice id">
                      <CopyId id={voice.id} label="voice id" />
                    </Fact>
                    <Fact label="ElevenLabs voice ID">
                      <CopyId id={voice.provider_voice_id} label="ElevenLabs voice ID" full />
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
                    {LANGUAGES.map((language) => {
                      const key = previewKey(language);
                      return (
                        <li key={language} className="flex items-center gap-3">
                          <Checkbox
                            id={`language-${language}`}
                            checked={draft.languages.includes(language)}
                            onCheckedChange={(on) => toggleLanguage(language, on)}
                          />
                          <label htmlFor={`language-${language}`} className="flex-1 text-sm">
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
                            onClick={() => settings && preview.toggle(key, settings, language)}
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
                      ElevenLabs does not list {joined(unlisted.map((l) => LANGUAGE_NAMES[l]))} for
                      this voice. Play the preview before you use it.
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

        <DialogFooter className="border-t px-6 py-4">
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
