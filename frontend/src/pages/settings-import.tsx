import { Download, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { exportSettings, useImportSettings } from "@/lib/queries";
import type { ImportResult } from "@/lib/types";

/** Export downloads the settings as YAML, without secrets. Import reads a file, lists what it
 * changes, and saves only after the user confirms. Every key in it is checked first: the keys
 * that pass are saved with the settings, and the dialog lists the ones that failed. */
export function ImportExport() {
  const input = useRef<HTMLInputElement>(null);
  const [document, setDocument] = useState<string | null>(null);
  const preview = useImportSettings();
  const apply = useImportSettings();
  const failed = apply.data?.failed.length ? apply.data : null;

  const download = async () => {
    try {
      const text = await exportSettings();
      const url = URL.createObjectURL(new Blob([text], { type: "application/yaml" }));
      const link = Object.assign(window.document.createElement("a"), {
        href: url,
        download: "yaksha-settings.yaml",
      });
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error("Could not export the settings", { description: String(error) });
    }
  };

  const read = async (file: File) => {
    const text = await file.text();
    setDocument(text);
    apply.reset();
    preview.mutate({ document: text, dryRun: true });
  };

  const close = () => {
    setDocument(null);
    preview.reset();
    apply.reset();
  };

  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".yaml,.yml,application/yaml,text/yaml"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void read(file);
        }}
      />
      <Button variant="outline" onClick={() => input.current?.click()}>
        <Upload />
        Import
      </Button>
      <Button variant="outline" onClick={() => void download()}>
        <Download />
        Export
      </Button>
      <Dialog open={document !== null} onOpenChange={(open) => !open && close()}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Import settings</DialogTitle>
          </DialogHeader>
          {failed ? (
            <Failed result={failed} />
          ) : preview.isPending ? (
            <p className="flex items-center gap-2 text-s-400 text-muted-foreground">
              <Spinner /> Reading the file
            </p>
          ) : preview.isError ? (
            <p className="text-s-400 text-destructive">{preview.error.message}</p>
          ) : (
            preview.data && <Changes result={preview.data} />
          )}
          {apply.isError && <p className="text-s-400 text-destructive">{apply.error.message}</p>}
          {failed ? (
            <DialogFooter>
              <Button onClick={close}>Done</Button>
            </DialogFooter>
          ) : (
            <DialogFooter>
              <Button variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button
                disabled={!preview.data || preview.data.changes.length === 0 || apply.isPending}
                onClick={() =>
                  document &&
                  apply.mutate(
                    { document, dryRun: false },
                    {
                      onSuccess: (result) => {
                        if (result.failed.length > 0) return;
                        toast.success("Settings imported");
                        close();
                      },
                    },
                  )
                }
              >
                {apply.isPending && <Spinner />}
                Check and import
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

const SECRET_LABELS: Record<string, string> = {
  llm_api_key: "LLM provider key",
  deepgram_api_key: "Deepgram key",
  elevenlabs_api_key: "ElevenLabs key",
  typesafe_api_key: "TypeSafe key",
  plivo_auth_id: "Plivo Auth ID",
  plivo_auth_token: "Plivo Auth token",
  trigger_signing_key: "Signing key",
};

/** A stored secret name as the page calls it. */
function secretLabel(name: string): string {
  return name.startsWith("trigger:")
    ? `Trigger secret ${name.slice("trigger:".length)}`
    : (SECRET_LABELS[name] ?? name);
}

/** A change line with its secret named as the page names it; a value change stays as it is. */
function changeLabel(change: string): string {
  const [name, rest] = change.split(/: (.*)/s);
  return name in SECRET_LABELS || name.startsWith("trigger:")
    ? `${secretLabel(name)}: ${rest}`
    : change;
}

function Changes({ result }: { result: ImportResult }) {
  const skipped = result.skipped.map((entry) => secretLabel(entry.split(" (")[0]));
  if (result.changes.length === 0 && skipped.length > 0) {
    return (
      <div className="grid gap-2 text-s-400">
        <p className="text-s-500">This file has no key values.</p>
        <p>
          An export holds placeholders like{" "}
          <code className="font-mono">{"${TRIGGER_SIGNING_KEY}"}</code>, not keys. Import a file
          with real values, or use the CLI to apply it with those variables set.
        </p>
        <SkippedList names={skipped} />
      </div>
    );
  }
  return (
    <div className="grid gap-3">
      {result.changes.length === 0 ? (
        <p className="text-s-400">Nothing to import.</p>
      ) : (
        <ul className="max-h-64 divide-y overflow-y-auto rounded-md border text-xs-400">
          {result.changes.map((change) => (
            <li key={change} className="px-3 py-1.5">
              {changeLabel(change)}
            </li>
          ))}
        </ul>
      )}
      {skipped.length > 0 && (
        <div className="grid gap-1 text-s-400">
          <p>
            Keys given as <code className="font-mono">{"${…}"}</code> were skipped. Your saved keys
            stay.
          </p>
          <SkippedList names={skipped} />
        </div>
      )}
    </div>
  );
}

/** After an import with keys that failed: what was saved, then each failed key and why. */
function Failed({ result }: { result: ImportResult }) {
  return (
    <div className="grid gap-3 text-s-400">
      {result.changes.length === 0 ? (
        <p>Nothing was saved.</p>
      ) : (
        <div className="grid gap-1">
          <p>Saved:</p>
          <ul className="max-h-40 divide-y overflow-y-auto rounded-md border text-xs-400">
            {result.changes.map((change) => (
              <li key={change} className="px-3 py-1.5">
                {changeLabel(change)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p>These keys failed their check and were not saved:</p>
      <ul className="max-h-64 divide-y overflow-y-auto rounded-md border text-xs-400">
        {result.failed.map((failure) => {
          const [names, reason] = failure.split(/: (.*)/s);
          return (
            <li key={failure} className="grid gap-0.5 px-3 py-1.5">
              <span className="text-xs-500">{names.split(", ").map(secretLabel).join(", ")}</span>
              <span className="text-destructive">{reason}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SkippedList({ names }: { names: string[] }) {
  return (
    <ul className="text-xs-400 text-muted-foreground">
      {names.map((name) => (
        <li key={name}>{name}</li>
      ))}
    </ul>
  );
}
