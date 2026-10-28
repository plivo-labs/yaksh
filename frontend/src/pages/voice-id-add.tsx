import { type KeyboardEvent, type SubmitEvent, useState } from "react";
import { createPortal } from "react-dom";

import { GenderBadge } from "@/components/gender-badge";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import type { CloseGuard } from "@/hooks/use-close-guard";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import { useAddVoice, useLookupVoice } from "@/lib/queries";
import { defaultSettings, spokenOf } from "@/lib/speech-providers";
import {
  type Language,
  type ProviderVoice,
  type TtsModel,
  type TtsTraits,
  VOICE_GENDER_ITEMS,
  type VoiceGender,
  voiceGender,
} from "@/lib/types";
import type { DialogPreview } from "@/pages/voice-dialog-shell";
import { VoiceFields } from "@/pages/voice-fields";

const GENDERS: { value: VoiceGender | "unset"; label: string }[] = [
  { value: "unset", label: "Not set" },
  ...VOICE_GENDER_ITEMS,
];

interface Draft {
  name: string;
  languages: Language[];
  /** Entered by hand for a voice that the provider does not describe. */
  gender: VoiceGender | null;
  accent: string;
}

const EMPTY_DRAFT: Draft = { name: "", languages: [], gender: null, accent: "" };

interface Details {
  providerVoiceId: string;
  gender: ProviderVoice["gender"];
  accent: string | null;
  listed: Language[];
}

/** One voice, entered by its ID. A provider with lookup fills the details from the ID; for the
 * others they are entered by hand. Its choices belong to one provider and model: the dialog gives
 * each pair a new form. */
export function VoiceIdAdd({
  traits,
  model,
  previews,
  guard,
  onDirtyChange,
  footer,
}: {
  traits: TtsTraits;
  /** Undefined until the account's models load, or when it has none. */
  model: TtsModel | undefined;
  previews: DialogPreview;
  guard: CloseGuard;
  /** Hears whether closing the dialog would lose the typed ID. */
  onDirtyChange: (dirty: boolean) => void;
  /** Where the buttons go: below the part of the dialog that scrolls. */
  footer: HTMLElement | null;
}) {
  const add = useAddVoice();
  const lookup = useLookupVoice();
  const [typedId, setTypedId] = useState("");
  const [found, setFound] = useState<Details | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [submitted, setSubmitted] = useState(false);
  const providerVoiceId = typedId.trim();

  const details: Details | null = traits.lookup
    ? found && found.providerVoiceId === providerVoiceId
      ? found
      : null
    : providerVoiceId
      ? {
          providerVoiceId,
          gender: draft.gender,
          accent: draft.accent.trim() || null,
          listed: [],
        }
      : null;

  const change = (next: Partial<Draft>) => {
    add.reset();
    setDraft((current) => ({ ...current, ...next }));
  };

  const changeId = (value: string) => {
    lookup.reset();
    add.reset();
    previews.stop();
    setTypedId(value);
    onDirtyChange(value.trim() !== "");
  };

  const getDetails = () => {
    if (!providerVoiceId || details || !model) return;
    lookup.mutate(
      { provider: traits.provider, id: providerVoiceId },
      {
        onSuccess: (answer) => {
          setFound({
            providerVoiceId,
            gender: answer.gender,
            accent: answer.accent,
            listed: answer.listed_languages,
          });
          change({ name: answer.name, languages: spokenOf(answer.listed_languages, model) });
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
    if (!details || !model) return;
    const name = draft.name.trim();
    const valid = Boolean(name) && draft.languages.length > 0;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    add.mutate(
      {
        name,
        languages: draft.languages,
        provider: traits.provider,
        provider_voice_id: details.providerVoiceId,
        model: model.id,
        ...(traits.lookup
          ? {}
          : { gender: details.gender, accent: details.accent, listed_languages: details.listed }),
      },
      { onSuccess: guard.close },
    );
  };

  return (
    <>
      {model && (
        <form id="voice-form" noValidate onSubmit={submit} className="flex flex-col gap-7">
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
                  disabled={!providerVoiceId || details !== null || lookup.isPending}
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

          {details && (
            <>
              {traits.lookup ? (
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
                      onValueChange={(next) => next && change({ gender: voiceGender(next) })}
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
                      onChange={(e) => change({ accent: e.target.value })}
                    />
                  </Field>
                </div>
              )}
              <VoiceFields
                draft={draft}
                onChange={change}
                model={model}
                spoken={defaultSettings(traits.provider, details.providerVoiceId, model.id)}
                listed={traits.lookup ? details.listed : null}
                providerLabel={traits.label}
                submitted={submitted}
                previews={previews}
              />
            </>
          )}
        </form>
      )}
      {footer &&
        createPortal(
          <>
            {add.error && <FieldError className="px-6 pb-3">{add.error.message}</FieldError>}
            <DialogFooter className="items-center border-t px-6 py-4">
              <span className="mr-auto text-xs-400 text-muted-foreground">
                Saving speaks a test line in this voice.
              </span>
              <Button type="button" variant="ghost" onClick={guard.requestClose}>
                Cancel
              </Button>
              <Button
                type="submit"
                form="voice-form"
                disabled={!details || !model || add.isPending}
              >
                {add.isPending && <Spinner />}
                Add voice
              </Button>
            </DialogFooter>
          </>,
          footer,
        )}
    </>
  );
}
