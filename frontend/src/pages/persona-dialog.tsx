import { Square, Play } from "lucide-react";
import { type ReactNode, type SubmitEvent, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import type { VoicePreview } from "@/hooks/use-voice-preview";
import { useDeletePersona, useSavePersona, useVoices } from "@/lib/queries";
import {
  LANGUAGE_NAMES,
  type Language,
  type Persona,
  type PersonaInput,
  type VoiceInfo,
} from "@/lib/types";

interface Draft {
  name: string;
  prompt: string;
  language: Language;
  voice_id: string;
  speed: number;
  stability: number;
}

const EMPTY: Draft = {
  name: "",
  prompt: "",
  language: "en",
  voice_id: "",
  speed: 1,
  stability: 0.5,
};

const APPEAR = "transition-opacity duration-150 ease-out starting:opacity-0";

const FORM = "form";

const languageItems = (Object.keys(LANGUAGE_NAMES) as Language[]).map((language) => ({
  value: language,
  label: LANGUAGE_NAMES[language],
}));

function toDraft(persona: Persona): Draft {
  return {
    name: persona.name,
    prompt: persona.prompt,
    language: persona.language,
    voice_id: persona.voice.id,
    speed: persona.voice.speed,
    stability: persona.voice.stability,
  };
}

function toInput(draft: Draft): PersonaInput {
  return {
    name: draft.name.trim(),
    prompt: draft.prompt.trim(),
    language: draft.language,
    voice: {
      provider: "elevenlabs",
      id: draft.voice_id.trim(),
      speed: draft.speed,
      stability: draft.stability,
    },
  };
}

function voiceLabel(voice: VoiceInfo): string {
  const details = [voice.gender, voice.accent].filter(Boolean).join(", ");
  return details ? `${voice.name} (${details})` : voice.name;
}

function SliderField({
  id,
  label,
  min,
  max,
  value,
  onChange,
  children,
}: {
  id: string;
  label: string;
  min: number;
  max: number;
  value: number;
  onChange: (value: number) => void;
  children?: ReactNode;
}) {
  return (
    <Field>
      <div className="flex items-baseline justify-between">
        <FieldLabel id={`${id}-label`}>{label}</FieldLabel>
        <span aria-hidden className="font-mono text-sm tabular-nums">
          {value.toFixed(2)}
        </span>
      </div>
      <Slider
        aria-labelledby={`${id}-label`}
        min={min}
        max={max}
        step={0.05}
        value={[value]}
        onValueChange={(next) => onChange((next as number[])[0])}
      />
      {children}
    </Field>
  );
}

export function PersonaDialog({
  persona,
  preview,
  onClosed,
}: {
  persona?: Persona;
  preview: VoicePreview;
  onClosed: () => void;
}) {
  const id = persona?.id;
  const save = useSavePersona(id);
  const remove = useDeletePersona();
  const [initial] = useState<Draft>(() => (persona ? toDraft(persona) : EMPTY));
  const [draft, setDraft] = useState<Draft>(initial);
  const [open, setOpen] = useState(true);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [missingVoice, setMissingVoice] = useState(false);
  const voices = useVoices(draft.language);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    save.reset();
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const listed = voices.data ?? [];
  const chosen = listed.find((voice) => voice.id === draft.voice_id);
  const voiceItems = listed.map((voice) => ({ value: voice.id, label: voiceLabel(voice) }));
  const hasVoice = draft.voice_id !== "";
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const input = toInput(draft);

  const requestClose = () => (dirty ? setConfirmingDiscard(true) : setOpen(false));

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    setMissingVoice(!hasVoice);
    if (!hasVoice) return;
    save.mutate(input, { onSuccess: () => setOpen(false) });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && requestClose()}
      onOpenChangeComplete={(next) => {
        if (next) return;
        preview.reset(FORM);
        onClosed();
      }}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>{id ? "Edit persona" : "New persona"}</DialogTitle>
        </DialogHeader>

        <form
          id="persona-form"
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 py-1"
        >
          <FieldGroup className="pb-6">
            <div className="grid gap-4 sm:grid-cols-[1fr_12rem]">
              <Field>
                <FieldLabel htmlFor="name">Name</FieldLabel>
                <Input
                  id="name"
                  required
                  maxLength={80}
                  value={draft.name}
                  onChange={(e) => set("name", e.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="language">Language</FieldLabel>
                <Select
                  items={languageItems}
                  value={draft.language}
                  onValueChange={(value) => value && set("language", value as Language)}
                >
                  <SelectTrigger id="language" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {languageItems.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="prompt">Behavior</FieldLabel>
              <Textarea
                id="prompt"
                rows={5}
                required
                maxLength={4000}
                placeholder="You are in a hurry. Give short answers and sometimes leave out a detail until the agent asks again."
                value={draft.prompt}
                onChange={(e) => set("prompt", e.target.value)}
              />
              <FieldDescription>
                Do not put the goal or facts here; each conversation gives the goal.
              </FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="voice">Voice</FieldLabel>
              <div className="flex gap-2">
                <Select
                  items={voiceItems}
                  value={chosen ? draft.voice_id : null}
                  onValueChange={(value) => value && set("voice_id", value)}
                  disabled={voices.isPending || voices.isPlaceholderData || voices.isError}
                >
                  <SelectTrigger id="voice" className="min-w-0 flex-1">
                    <SelectValue
                      placeholder={
                        voices.isPending
                          ? "Loading voices"
                          : voices.isError
                            ? "Voices did not load"
                            : draft.voice_id
                              ? "Voice not in this list"
                              : "Choose a voice"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {voiceItems.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  aria-label={preview.isPlaying(FORM) ? "Stop preview" : "Preview voice"}
                  disabled={!hasVoice}
                  aria-busy={preview.isLoading(FORM)}
                  onClick={() => preview.toggle(FORM, input.voice, input.language)}
                >
                  {preview.isLoading(FORM) ? (
                    <Spinner />
                  ) : preview.isPlaying(FORM) ? (
                    <Square />
                  ) : (
                    <Play />
                  )}
                </Button>
              </div>
              {missingVoice && !hasVoice && (
                <FieldError className={APPEAR}>Choose a voice.</FieldError>
              )}
              {voices.isError && (
                <FieldError className={APPEAR}>
                  Could not load voices: {voices.error.message}
                </FieldError>
              )}
              {preview.error(FORM) && (
                <FieldError className={APPEAR}>{preview.error(FORM)}</FieldError>
              )}
            </Field>

            <div className="grid gap-6 sm:grid-cols-2">
              <SliderField
                id="speed"
                label="Speed"
                min={0.7}
                max={1.2}
                value={draft.speed}
                onChange={(value) => set("speed", value)}
              />
              <SliderField
                id="stability"
                label="Stability"
                min={0}
                max={1}
                value={draft.stability}
                onChange={(value) => set("stability", value)}
              >
                <FieldDescription>
                  Lower values make each call sound more different; 0.5 is the default.
                </FieldDescription>
              </SliderField>
            </div>
          </FieldGroup>
        </form>

        {(save.error || remove.error) && (
          <FieldError className={`px-6 pb-3 ${APPEAR}`}>
            {(save.error ?? remove.error)?.message}
          </FieldError>
        )}

        <DialogFooter className="border-t px-6 py-4">
          {id && (
            <AlertDialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
              <AlertDialogTrigger
                render={
                  <Button type="button" variant="ghost" className="text-destructive sm:mr-auto" />
                }
              >
                Delete
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete {initial.name}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Past and queued conversations are not changed.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep</AlertDialogCancel>
                  <AlertDialogAction
                    disabled={remove.isPending}
                    onClick={() =>
                      remove.mutate(id, {
                        onSuccess: () => setOpen(false),
                        onSettled: () => setConfirmingDelete(false),
                      })
                    }
                  >
                    {remove.isPending && <Spinner />}
                    Delete
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
          <Button type="button" variant="ghost" onClick={requestClose}>
            Cancel
          </Button>
          <Button type="submit" form="persona-form" disabled={save.isPending}>
            {save.isPending && <Spinner />}
            {id ? "Save changes" : "Create persona"}
          </Button>
        </DialogFooter>

        <AlertDialog open={confirmingDiscard} onOpenChange={setConfirmingDiscard}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Discard changes?</AlertDialogTitle>
              <AlertDialogDescription>
                Your changes to this persona are not saved.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep editing</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  setConfirmingDiscard(false);
                  setOpen(false);
                }}
              >
                Discard
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </DialogContent>
    </Dialog>
  );
}
