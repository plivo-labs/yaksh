import { type SubmitEvent, useState } from "react";

import { DeleteConfirm } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { GenderBadge } from "@/components/gender-badge";
import { Fact } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { FieldError, FieldGroup } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { useCloseGuard } from "@/hooks/use-close-guard";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import { useDeleteVoice, useEditVoice } from "@/lib/queries";
import { defaultSettings, ttsModel } from "@/lib/speech-providers";
import type { TtsTraits, Voice, VoiceEdit } from "@/lib/types";
import { type DialogPreview, VoiceDialogBody, VoiceDialogShell } from "@/pages/voice-dialog-shell";
import { VoiceFields } from "@/pages/voice-fields";

/** A voice in the list: its name and languages change; its provider, ID and model do not. */
export function VoiceEditDialog({
  voice,
  traits,
  previews,
  onClosed,
}: {
  voice: Voice;
  traits: TtsTraits;
  previews: DialogPreview;
  onClosed: () => void;
}) {
  const edit = useEditVoice();
  const remove = useDeleteVoice();
  const [initial] = useState<VoiceEdit>(() => ({ name: voice.name, languages: voice.languages }));
  const [draft, setDraft] = useState(initial);
  const [submitted, setSubmitted] = useState(false);
  const guard = useCloseGuard(JSON.stringify(draft) !== JSON.stringify(initial));
  /** A saved voice keeps its model, also one that the account no longer offers. */
  const model = ttsModel(traits, voice.model) ?? traits.models[0];

  const change = (next: Partial<VoiceEdit>) => {
    edit.reset();
    setDraft((current) => ({ ...current, ...next }));
  };

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = draft.name.trim();
    const valid = Boolean(name) && draft.languages.length > 0;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    edit.mutate({ id: voice.id, name, languages: draft.languages }, { onSuccess: guard.close });
  };

  return (
    <VoiceDialogShell title="Edit voice" guard={guard} onClosed={onClosed}>
      <VoiceDialogBody>
        <form id="voice-form" noValidate onSubmit={submit}>
          <FieldGroup>
            <div className={`flex flex-wrap items-center gap-2 text-p-400 ${APPEAR}`}>
              {voice.gender && <GenderBadge gender={voice.gender} />}
              {voice.accent && (
                <span className="text-muted-foreground capitalize">{voice.accent}</span>
              )}
            </div>
            <dl className="flex flex-wrap gap-x-10 gap-y-3">
              <Fact label="Voice id">
                <CopyId id={voice.id} label="voice id" />
              </Fact>
              <Fact label={`${traits.label} voice ID`}>
                <CopyId id={voice.provider_voice_id} label={`${traits.label} voice ID`} full />
              </Fact>
              {voice.model !== null && (
                <Fact label="Model">{ttsModel(traits, voice.model)?.label ?? voice.model}</Fact>
              )}
            </dl>
            <VoiceFields
              draft={draft}
              onChange={change}
              model={model}
              spoken={defaultSettings(voice.provider, voice.provider_voice_id, voice.model)}
              listed={
                traits.lookup || voice.listed_languages.length > 0 ? voice.listed_languages : null
              }
              providerLabel={traits.label}
              submitted={submitted}
              previews={previews}
            />
          </FieldGroup>
        </form>
      </VoiceDialogBody>

      {(edit.error || remove.error) && (
        <FieldError className="px-6 pb-3">{(edit.error ?? remove.error)?.message}</FieldError>
      )}

      <DialogFooter className="items-center border-t px-6 py-4">
        <DeleteConfirm
          name={initial.name}
          description="Personas that use this voice keep it."
          pending={remove.isPending}
          onDelete={(close) =>
            remove.mutate(voice.id, { onSuccess: guard.close, onSettled: close })
          }
        />
        <Button type="button" variant="ghost" onClick={guard.requestClose}>
          Cancel
        </Button>
        <Button type="submit" form="voice-form" disabled={edit.isPending}>
          {edit.isPending && <Spinner />}
          Save changes
        </Button>
      </DialogFooter>
    </VoiceDialogShell>
  );
}
