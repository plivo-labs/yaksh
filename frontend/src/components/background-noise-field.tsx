import type { ReactNode } from "react";

import { Segmented } from "@/components/segmented";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type BackgroundNoise,
  NO_NOISE,
  NOISE_LEVEL_ITEMS,
  NOISE_SOUND_ITEMS,
  type NoiseSound,
} from "@/lib/types";

const INHERIT = "inherit";

/** A sound and its level. With `inherit`, the first choice is null: the persona's setting. */
export function BackgroundNoiseField({
  id,
  value,
  onChange,
  inherit,
  action,
  error,
}: {
  id: string;
  value: BackgroundNoise | null;
  onChange: (value: BackgroundNoise | null) => void;
  inherit?: string;
  action?: ReactNode;
  error?: string | null;
}) {
  const items = [...(inherit ? [{ value: INHERIT, label: inherit }] : []), ...NOISE_SOUND_ITEMS];
  const pick = (sound: string | null) => {
    if (sound === null) return;
    if (sound === INHERIT) onChange(null);
    else if (sound === "none") onChange(NO_NOISE);
    else onChange({ sound: sound as NoiseSound, level: value?.level ?? NO_NOISE.level });
  };
  return (
    <Field>
      <FieldLabel htmlFor={id}>Background noise</FieldLabel>
      <div className="flex gap-2">
        <Select items={items} value={value?.sound ?? INHERIT} onValueChange={pick}>
          <SelectTrigger id={id} className="min-w-0 flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {items.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        {action}
      </div>
      {value && value.sound !== "none" && (
        <Segmented
          label="Level"
          value={value.level}
          options={NOISE_LEVEL_ITEMS}
          onChange={(level) => onChange({ ...value, level })}
        />
      )}
      <FieldDescription>
        Plays behind the caller for the whole call. Light, busy and loud put the caller's voice
        about 20, 10 and 5 dB above the noise.
      </FieldDescription>
      {error && <FieldError>{error}</FieldError>}
    </Field>
  );
}
