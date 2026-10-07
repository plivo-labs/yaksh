import { Download, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { exportSettings, useImportSettings } from "@/lib/queries";
import type { ImportResult } from "@/lib/types";

/** Export downloads the settings as YAML, without secrets. Import reads a file, lists what it
 * changes, and saves only after the user confirms; every key in it is checked first. */
export function ImportExport() {
  const input = useRef<HTMLInputElement>(null);
  const [document, setDocument] = useState<string | null>(null);
  const preview = useImportSettings();
  const apply = useImportSettings();

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
            <DialogDescription>
              Yaksha checks every key in the file with its provider. It saves nothing unless every
              check passes.
            </DialogDescription>
          </DialogHeader>
          {preview.isPending ? (
            <p className="flex items-center gap-2 text-s-400 text-muted-foreground">
              <Spinner /> Reading the file
            </p>
          ) : preview.isError ? (
            <p className="text-s-400 text-destructive">{preview.error.message}</p>
          ) : (
            preview.data && <Changes result={preview.data} />
          )}
          {apply.isError && <p className="text-s-400 text-destructive">{apply.error.message}</p>}
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
                    onSuccess: () => {
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
        </DialogContent>
      </Dialog>
    </>
  );
}

function Changes({ result }: { result: ImportResult }) {
  return (
    <div className="grid gap-3">
      {result.changes.length === 0 ? (
        <p className="text-s-400">The file changes nothing.</p>
      ) : (
        <ul className="max-h-64 divide-y overflow-y-auto rounded-md border font-mono text-xs-400">
          {result.changes.map((change) => (
            <li key={change} className="px-3 py-1.5">
              {change}
            </li>
          ))}
        </ul>
      )}
      {result.skipped.length > 0 && (
        <div className="grid gap-1 text-s-400">
          <p>Not imported: the browser cannot read environment variables. Use the CLI for these.</p>
          <ul className="font-mono text-xs-400 text-muted-foreground">
            {result.skipped.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
