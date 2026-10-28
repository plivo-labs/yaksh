import { Play, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { joined } from "@/lib/format";
import { APPEAR } from "@/lib/motion";
import {
  LANGUAGE_NAMES,
  type Language,
  type TtsModel,
  type VoiceEdit,
  type VoiceSettings,
} from "@/lib/types";
import type { DialogPreview } from "@/pages/voice-dialog-shell";

/** The longest name the server takes, in code points. */
export const NAME_MAX = 80;

const previewKey = (language: Language) => `voice:${language}`;

/** A voice's name and the model's languages to use it for, each with a preview in the voice. */
export function VoiceFields({
  draft,
  onChange,
  model,
  spoken,
  listed,
  providerLabel,
  submitted,
  previews,
}: {
  draft: VoiceEdit;
  onChange: (next: Partial<VoiceEdit>) => void;
  model: TtsModel;
  /** The voice as the previews speak it. */
  spoken: VoiceSettings;
  /** The languages that the provider lists for the voice; null when they are not known. */
  listed: Language[] | null;
  providerLabel: string;
  submitted: boolean;
  previews: DialogPreview;
}) {
  const unlisted = listed ? draft.languages.filter((language) => !listed.includes(language)) : [];
  const previewError = model.languages
    .map((language) => previews.error(previewKey(language)))
    .find(Boolean);

  const toggleLanguage = (language: Language, on: boolean) =>
    onChange({
      languages: model.languages.filter((item) =>
        item === language ? on : draft.languages.includes(item),
      ),
    });

  return (
    <>
      <Field className={APPEAR}>
        <FieldLabel htmlFor="voice-name">Name</FieldLabel>
        <Input
          id="voice-name"
          required
          maxLength={NAME_MAX}
          aria-invalid={submitted && !draft.name.trim()}
          value={draft.name}
          onChange={(e) => onChange({ name: e.target.value })}
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
                    previews.isPlaying(key)
                      ? `Stop ${LANGUAGE_NAMES[language]} preview`
                      : `Play ${LANGUAGE_NAMES[language]} preview`
                  }
                  aria-busy={previews.isLoading(key)}
                  onClick={() => previews.play(key, spoken, language)}
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
        {unlisted.length > 0 && (
          <FieldDescription className={APPEAR}>
            {providerLabel} does not list {joined(unlisted.map((l) => LANGUAGE_NAMES[l]))} for this
            voice. Play the preview before you use it.
          </FieldDescription>
        )}
        {submitted && draft.languages.length === 0 && (
          <FieldError>Choose at least one language.</FieldError>
        )}
        {previewError && <FieldError>{previewError}</FieldError>}
      </FieldSet>
    </>
  );
}
