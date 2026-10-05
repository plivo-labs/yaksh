import { Download, FileText, Plus, Upload } from "lucide-react";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { ActionPanel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useCloseGuard } from "@/hooks/use-close-guard";
import { textSize } from "@/lib/format";
import { type KnowledgeBaseSource, useSavedKnowledgeBase } from "@/hooks/use-knowledge-base";
import { APPEAR } from "@/lib/motion";
import { createTextDocument, downloadDocument, uploadDocument, useDocument } from "@/lib/queries";
import type {
  Agent,
  DocumentSummary,
  KnowledgeBaseDocument,
  KnowledgeBaseEntry,
} from "@/lib/types";

const MAX_DOCUMENTS = 20;
const MAX_TEXT_CHARS = 1_000_000;
const MAX_NAME_CHARS = 200;

const EXTENSIONS = [".pdf", ".txt", ".md"];

/** The extension as the server reads it: control characters dropped, the name trimmed, then
 * Python's `PurePath.suffix`, where leading dots are part of the name. */
function suffix(name: string): string {
  const base = name
    .replaceAll(/\p{Cc}/gu, "")
    .trim()
    .replace(/^\.+/, "");
  const dot = base.lastIndexOf(".");
  return dot === -1 ? "" : base.slice(dot).toLowerCase();
}

function supported(name: string): boolean {
  return EXTENSIONS.includes(suffix(name));
}

function carriesFiles(event: DragEvent): boolean {
  return event.dataTransfer.types.includes("Files");
}

const TYPE_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "text/plain": "Text file",
  "text/markdown": "Markdown file",
};

/** The name, or the name with " (2)", " (3)"… when the knowledge base already uses it,
 * kept within the name limit. Compared lowercase, as the server does. */
function freeName(name: string, taken: Set<string>): string {
  let candidate = name;
  for (let n = 2; taken.has(candidate.toLowerCase()); n++) {
    const suffix = ` (${n})`;
    candidate = `${name.slice(0, MAX_NAME_CHARS - suffix.length)}${suffix}`;
  }
  taken.add(candidate.toLowerCase());
  return candidate;
}

function details(document: KnowledgeBaseDocument): string {
  const type = document.media_type ? TYPE_LABELS[document.media_type] : "Pasted text";
  const pages = document.pages === null ? "" : `, ${document.pages} pages`;
  return `${type}, ${textSize(document.characters)}${pages}`;
}

export function AgentKnowledgeBase({ agent }: { agent: Agent }) {
  return <KnowledgeBasePanel source={useSavedKnowledgeBase(agent)} />;
}

/** `title` names the panel where no tab does. */
export function KnowledgeBasePanel({
  source,
  title,
}: {
  source: KnowledgeBaseSource;
  title?: string;
}) {
  const files = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState<KnowledgeBaseDocument | "new" | null>(null);
  const { documents, progress, setProgress } = source;
  const busy = progress !== null || source.saving;
  const room = MAX_DOCUMENTS - documents.length;
  const depth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const refusal = busy
    ? "Wait for the current upload to finish."
    : room <= 0
      ? `The knowledge base holds at most ${MAX_DOCUMENTS} documents.`
      : null;

  // A file dropped next to the panel would make the browser open it and lose the page.
  useEffect(() => {
    const refuse = (event: globalThis.DragEvent) => {
      if (event.defaultPrevented || !event.dataTransfer?.types.includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "none";
    };
    window.addEventListener("dragover", refuse);
    window.addEventListener("drop", refuse);
    return () => {
      window.removeEventListener("dragover", refuse);
      window.removeEventListener("drop", refuse);
    };
  }, []);

  const addFiles = async (picked: File[]) => {
    const readable = picked.filter((file) => supported(file.name));
    const failed = [
      ...picked
        .filter((file) => !supported(file.name))
        .map((file) => `${file.name}: add PDF, TXT or MD files`),
      ...readable
        .slice(room)
        .map((file) => `${file.name}: the knowledge base holds at most ${MAX_DOCUMENTS} documents`),
    ];
    const taken = new Set(documents.map((document) => document.name.toLowerCase()));
    const added: KnowledgeBaseEntry[] = [];
    const uploaded: DocumentSummary[] = [];
    const accepted = readable.slice(0, room);
    for (const [index, file] of accepted.entries()) {
      setProgress(`Reading ${file.name} (${index + 1} of ${accepted.length})`);
      try {
        const document = await uploadDocument(file);
        added.push({ document_id: document.id, name: freeName(document.name, taken) });
        uploaded.push(document);
      } catch (error) {
        failed.push(`${file.name}: ${(error as Error).message}`);
      }
    }
    if (added.length > 0) {
      setProgress("Saving the knowledge base");
      try {
        await source.change((current) => [...current, ...added], uploaded);
      } catch (error) {
        failed.push((error as Error).message);
      }
    }
    if (failed.length > 0) {
      toast.error("Some documents were not added", { description: failed.join("\n") });
    }
    setProgress(null);
  };

  const download = async (document: KnowledgeBaseDocument) => {
    try {
      await downloadDocument(document.document_id, document.name);
    } catch (error) {
      toast.error(`Could not download ${document.name}`, {
        description: (error as Error).message,
      });
    }
  };

  const remove = async (target: KnowledgeBaseDocument) => {
    try {
      await source.change(
        (current) => current.filter((entry) => entry.document_id !== target.document_id),
        [],
      );
    } catch (error) {
      toast.error(`Could not delete ${target.name}`, { description: (error as Error).message });
    }
  };

  const dropTarget = {
    onDragEnter: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    onDragOver: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = refusal ? "none" : "copy";
    },
    onDragLeave: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    onDrop: (event: DragEvent<HTMLElement>) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      if (!refusal) void addFiles(Array.from(event.dataTransfer.files));
    },
  };

  const addButtons = (
    <div className="flex gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={room <= 0 || busy}
        onClick={() => setOpen("new")}
      >
        <Plus />
        Add text
      </Button>
      <Button
        type="button"
        variant={documents.length > 0 ? "outline" : "default"}
        size="sm"
        disabled={room <= 0 || busy}
        onClick={() => files.current?.click()}
      >
        <Upload />
        Add documents
      </Button>
    </div>
  );

  return (
    <>
      <input
        ref={files}
        type="file"
        accept={EXTENSIONS.join(",")}
        multiple
        hidden
        onChange={(e) => {
          void addFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
      <ActionPanel
        title={
          title && (
            <>
              {title}{" "}
              <span className="font-normal text-muted-foreground tabular-nums">
                {documents.length}
              </span>
            </>
          )
        }
        action={addButtons}
        notice={
          progress && (
            <p className="flex items-center gap-2 px-5 pt-4 text-p-400 text-muted-foreground">
              <Spinner />
              {progress}
            </p>
          )
        }
        className="relative"
        {...dropTarget}
      >
        {documents.length === 0 ? (
          <div className="flex flex-1 flex-col p-5">
            <div className="grid flex-1 content-center justify-items-center gap-4 rounded-lg border border-dashed px-6 py-8 text-center">
              <span className="grid size-10 place-items-center rounded-full bg-muted text-muted-foreground">
                <Upload className="size-4" />
              </span>
              <div className="grid gap-1">
                <p className="text-p-400 font-medium">Drop PDF, TXT or MD files here</p>
                <p className="text-p-400 text-muted-foreground">
                  Add the FAQ, policies or product facts the agent answers from.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <ul className="divide-y">
            {documents.map((document) => (
              <li
                key={document.document_id}
                className="flex items-center gap-3 px-5 py-3.5 transition-colors duration-150 hover:bg-hv1 has-[>button:active]:bg-muted"
              >
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <button
                  type="button"
                  onClick={() => setOpen(document)}
                  className="grid min-w-0 flex-1 gap-0.5 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  <span className="truncate text-s-500">{document.name}</span>
                  <span className="truncate text-xs-400 text-muted-foreground tabular-nums">
                    {details(document)}
                  </span>
                  {Boolean(document.empty_pages) && (
                    <span className="text-xs-400 text-status-warning">
                      {document.empty_pages} of {document.pages} pages had no text (scanned?)
                    </span>
                  )}
                </button>
                {document.media_type && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Download ${document.name}`}
                    onClick={() => void download(document)}
                  >
                    <Download />
                  </Button>
                )}
                {source.deleteNote ? (
                  <DeleteConfirm
                    name={document.name}
                    description={source.deleteNote}
                    pending={busy}
                    onDelete={(close) => void remove(document).finally(close)}
                  />
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    className="text-destructive"
                    disabled={busy}
                    onClick={() => void remove(document)}
                  >
                    Remove
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        {dragging && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-lg border-2 border-dashed border-primary/40 bg-background/85 backdrop-blur-[2px] transition-opacity duration-150 ease-out starting:opacity-0"
          >
            <p className="flex items-center gap-2 px-6 text-p-400 font-medium">
              <Upload className="size-4 shrink-0" />
              {refusal ?? "Drop to add to the knowledge base"}
            </p>
          </div>
        )}
      </ActionPanel>
      {open !== null && (
        <DocumentSheet
          key={open === "new" ? "new" : open.document_id}
          document={open === "new" ? undefined : open}
          documents={documents}
          saving={busy}
          onSave={source.change}
          onClosed={() => setOpen(null)}
        />
      )}
    </>
  );
}

/** Shows a document's text and saves a new name or new text. New text becomes a new pasted
 * document, because a document never changes once earlier agent versions refer to it. */
function DocumentSheet({
  document,
  documents,
  saving,
  onSave,
  onClosed,
}: {
  document?: KnowledgeBaseDocument;
  documents: KnowledgeBaseDocument[];
  saving: boolean;
  onSave: KnowledgeBaseSource["change"];
  onClosed: () => void;
}) {
  const loaded = useDocument(document?.document_id);
  const [name, setName] = useState(document?.name ?? "");
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const guard = useCloseGuard(text !== null || name !== (document?.name ?? ""));
  const requestClose = () => !working && guard.requestClose();
  const shownText = text ?? loaded.data?.text ?? "";
  const others = documents.filter((other) => other.document_id !== document?.document_id);
  const clash = others.some((other) => other.name.toLowerCase() === name.trim().toLowerCase());
  const tooLong = shownText.length > MAX_TEXT_CHARS;

  const submit = async () => {
    setError(null);
    setWorking(true);
    try {
      const trimmed = name.trim();
      const saved =
        document && text === null
          ? { id: document.document_id, added: [] }
          : await createTextDocument(trimmed, shownText).then((created) => ({
              id: created.id,
              added: [created],
            }));
      const entry = { document_id: saved.id, name: trimmed };
      await onSave(
        (current) =>
          document
            ? current.map((other) => (other.document_id === document.document_id ? entry : other))
            : [...current, entry],
        saved.added,
      );
      guard.close();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setWorking(false);
    }
  };

  return (
    <Sheet
      open={guard.open}
      onOpenChange={(next) => !next && requestClose()}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <SheetContent size="lg" className="gap-0">
        <SheetHeader>
          <SheetTitle>{document ? document.name : "Add text"}</SheetTitle>
          <SheetDescription>
            {document ? details(document) : "Paste text the agent answers from."}
          </SheetDescription>
        </SheetHeader>
        <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-4 px-6">
          <Field>
            <FieldLabel htmlFor="document-name">Name</FieldLabel>
            <Input
              id="document-name"
              maxLength={200}
              disabled={working}
              aria-invalid={clash}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {clash && (
              <FieldError>Another document in this knowledge base has this name.</FieldError>
            )}
          </Field>
          <Field className="min-h-0 grid-rows-[auto_minmax(0,1fr)_auto]">
            <FieldLabel htmlFor="document-text">Text</FieldLabel>
            {document && loaded.isPending ? (
              <Skeleton className="h-full" />
            ) : (
              <Textarea
                id="document-text"
                className="h-full resize-none font-mono text-xs-400"
                aria-invalid={tooLong}
                disabled={working}
                value={shownText}
                onChange={(e) => setText(e.target.value)}
              />
            )}
            {tooLong ? (
              <FieldError>
                The text has {shownText.length.toLocaleString()} characters; the limit is{" "}
                {MAX_TEXT_CHARS.toLocaleString()}.
              </FieldError>
            ) : (
              document?.media_type &&
              text !== null && (
                <FieldDescription className={APPEAR}>
                  Edited text is saved as pasted text, and the original file is no longer linked.
                </FieldDescription>
              )
            )}
          </Field>
          {(error || loaded.error) && <FieldError>{error ?? loaded.error?.message}</FieldError>}
        </div>
        <SheetFooter className="flex-row justify-end">
          <Button type="button" variant="ghost" disabled={working} onClick={requestClose}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={working || saving || clash || tooLong || !name.trim() || !shownText.trim()}
            onClick={() => void submit()}
          >
            {working && <Spinner />}
            {document ? "Save" : "Add"}
          </Button>
        </SheetFooter>
        <DiscardConfirm subject="document" {...guard.discard} />
      </SheetContent>
    </Sheet>
  );
}
