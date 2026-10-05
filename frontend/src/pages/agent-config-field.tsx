import { Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { textSize } from "@/lib/format";
import { APPEAR } from "@/lib/motion";

export const MAX_CONFIG_CHARS = 1_000_000;

/** The agent's full configuration as text, typed, pasted or read from a file. */
export function ConfigField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const file = useRef<HTMLInputElement>(null);
  const [unreadable, setUnreadable] = useState<string | null>(null);

  const load = async (picked: File | undefined) => {
    if (!picked) return;
    try {
      onChange(await picked.text());
      setUnreadable(null);
    } catch {
      setUnreadable(`Could not read ${picked.name}.`);
    }
  };

  return (
    <Field>
      <div className="flex items-end justify-between gap-3">
        <FieldLabel htmlFor="config">Config</FieldLabel>
        <Button type="button" variant="outline" size="sm" onClick={() => file.current?.click()}>
          <Upload />
          Upload file
        </Button>
        <input
          ref={file}
          type="file"
          accept=".txt,.md,.json,.yaml,.yml"
          hidden
          onChange={(e) => {
            void load(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      <Textarea
        id="config"
        rows={8}
        className="max-h-96 font-mono text-xs-400"
        placeholder="The agent's prompt, a flow export or an assistant definition, as text."
        aria-invalid={value.length > MAX_CONFIG_CHARS}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value.length > MAX_CONFIG_CHARS ? (
        <FieldError>
          The config has {value.length.toLocaleString()} characters; the limit is{" "}
          {MAX_CONFIG_CHARS.toLocaleString()}.
        </FieldError>
      ) : (
        value && <FieldDescription className={APPEAR}>{textSize(value.length)}.</FieldDescription>
      )}
      {unreadable && <FieldError>{unreadable}</FieldError>}
    </Field>
  );
}
