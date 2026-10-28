import { useRef, useState } from "react";

import { Segmented } from "@/components/segmented";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
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
import { joined } from "@/lib/format";
import { useAddVoices, useSettings, useVoiceModels } from "@/lib/queries";
import { CUTS_AT_SENTENCES, TTS_PROVIDERS, hasCredential, ttsTraits } from "@/lib/speech-providers";
import {
  LANGUAGE_NAMES,
  type TtsModel,
  type TtsTraits,
  type Voice,
  type VoiceProvider,
} from "@/lib/types";
import { VoiceCatalogAdd } from "@/pages/voice-catalog-add";
import { type DialogPreview, VoiceDialogShell } from "@/pages/voice-dialog-shell";
import { VoiceEditDialog } from "@/pages/voice-edit-dialog";
import { VoiceIdAdd } from "@/pages/voice-id-add";

type Mode = "find" | "id";
const MODES: { value: Mode; label: string }[] = [
  { value: "find", label: "Find a voice" },
  { value: "id", label: "Enter an ID" },
];

/** What sets a model apart from the provider's other models: its speeds and its languages. */
function modelHint(model: TtsModel): string {
  const speed =
    model.speed_min === model.speed_max
      ? "No speed setting."
      : `Speed ${model.speed_min.toFixed(2)} to ${model.speed_max.toFixed(2)}.`;
  return `${speed} Speaks ${joined(model.languages.map((language) => LANGUAGE_NAMES[language]))}.`;
}

/** Add voices of any text-to-speech provider with a key, or edit one in the list. The server
 * speaks a line in each voice and model before it saves it. */
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
  /** The previews this dialog started, so that closing it or changing the voice stops them. */
  const played = useRef(new Set<string>());
  const previews: DialogPreview = {
    isPlaying: preview.isPlaying,
    isLoading: preview.isLoading,
    error: preview.error,
    play: (key, spoken, language) => {
      played.current.add(key);
      preview.toggle(key, spoken, language);
    },
    stop: () => {
      for (const key of played.current) preview.reset(key);
    },
  };
  const closed = () => {
    previews.stop();
    onClosed();
  };
  return voice ? (
    <VoiceEditDialog
      voice={voice}
      traits={ttsTraits(providers, voice.provider)}
      previews={previews}
      onClosed={closed}
    />
  ) : (
    <VoiceAddDialog providers={providers} previews={previews} onClosed={closed} />
  );
}

/** New voices get one of the models that the provider's account has: several picked from the
 * provider's voices, or one entered by its ID. */
function VoiceAddDialog({
  providers,
  previews,
  onClosed,
}: {
  providers: TtsTraits[];
  previews: DialogPreview;
  onClosed: () => void;
}) {
  const settings = useSettings();
  /** The batch of picked voices. While it runs, the dialog and the choices that made it stay. */
  const addPicked = useAddVoices();
  const adding = addPicked.isPending;
  const [provider, setProvider] = useState<VoiceProvider>(
    () =>
      TTS_PROVIDERS.find((item) => hasCredential(item, settings.data?.secrets))?.value ??
      "elevenlabs",
  );
  const traits = ttsTraits(providers, provider);
  const offered = useVoiceModels(provider);
  /** The model the person chose; until then, the first one offered. */
  const [modelChoice, setModelChoice] = useState<string>();
  /** A model once the account's models load, and only if the account has one. A failed refresh
   * keeps the models that loaded, so the add form keeps its choices. */
  const model = offered.data?.find((item) => item.id === modelChoice) ?? offered.data?.[0];
  /** Why a new voice cannot get a model. */
  const modelProblem = offered.data
    ? offered.data.length === 0
      ? `This ${traits.label} account has no model that Yaksh can use.`
      : null
    : offered.isError
      ? offered.error.message
      : null;
  const choosesModel = traits.models.some((item) => item.id !== null);
  const [mode, setMode] = useState<Mode>("find");
  /** The key of the add form. A voice is valid only for its provider and model (Sarvam's speakers
   * differ by model), so each pair gets a new form, and nothing picked for one is added with
   * another. */
  const form = `${mode}:${provider}:${model?.id ?? ""}`;
  /** Whether the add form holds choices that closing the dialog would lose. A new form has none. */
  const [unsaved, setUnsaved] = useState({ form, dirty: false });
  if (unsaved.form !== form) setUnsaved({ form, dirty: false });
  const guard = useCloseGuard(unsaved.dirty);
  const onDirtyChange = (dirty: boolean) => setUnsaved({ form, dirty });

  const chooseProvider = (next: VoiceProvider) => {
    previews.stop();
    setProvider(next);
    setModelChoice(undefined);
  };

  const chooseModel = (next: string) => {
    previews.stop();
    setModelChoice(next);
  };

  const chooseMode = (next: Mode) => {
    if (next === mode) return;
    previews.stop();
    setMode(next);
  };

  return (
    <VoiceDialogShell title="Add voice" guard={guard} locked={adding} onClosed={onClosed}>
      <FieldGroup className="px-6 pb-3">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="voice-provider">Provider</FieldLabel>
            <Select
              items={TTS_PROVIDERS.map((item) => ({ value: item.value, label: item.label }))}
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
          {(choosesModel || modelProblem !== null) && (
            <Field>
              <FieldLabel htmlFor={modelProblem === null ? "voice-model" : undefined}>
                Model
              </FieldLabel>
              {modelProblem !== null ? (
                <FieldError>{modelProblem}</FieldError>
              ) : (
                <Select
                  items={(offered.data ?? []).map((item) => ({
                    value: item.id,
                    label: item.label,
                  }))}
                  value={model?.id ?? null}
                  disabled={adding || !model}
                  onValueChange={(next) => next && chooseModel(next)}
                >
                  <SelectTrigger id="voice-model" className="w-full">
                    {model ? <SelectValue /> : <Spinner />}
                  </SelectTrigger>
                  <SelectContent>
                    {offered.data?.map((item) => (
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
              )}
              {model && model.speed_min === model.speed_max && (
                <FieldDescription>This model takes no speed setting.</FieldDescription>
              )}
            </Field>
          )}
        </div>

        <Segmented
          label="Voice"
          value={mode}
          options={MODES}
          disabled={adding}
          onChange={chooseMode}
        />
      </FieldGroup>
      {mode === "find" ? (
        <VoiceCatalogAdd
          key={form}
          traits={traits}
          model={model}
          previews={previews}
          addPicked={addPicked}
          guard={guard}
          onDirtyChange={onDirtyChange}
        />
      ) : (
        <VoiceIdAdd
          key={form}
          traits={traits}
          model={model}
          previews={previews}
          guard={guard}
          onDirtyChange={onDirtyChange}
        />
      )}
    </VoiceDialogShell>
  );
}
