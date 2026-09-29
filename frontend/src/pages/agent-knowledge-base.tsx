import { Download, FileText, Plus, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
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
import {
  createTextDocument,
  downloadDocument,
  uploadDocument,
  useDocument,
  useSaveKnowledgeBase,
} from "@/lib/queries";
import type { Agent, KnowledgeBaseDocument, KnowledgeBaseEntry } from "@/lib/types";

const MAX_DOCUMENTS = 20;
const MAX_TEXT_CHARS = 1_000_000;
const MAX_NAME_CHARS = 200;

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
  const save = useSaveKnowledgeBase(agent.id);
  const files = useRef<HTMLInputElement>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [open, setOpen] = useState<KnowledgeBaseDocument | "new" | null>(null);
  const documents = agent.knowledge_base;
  const busy = adding !== null || save.isPending;
  const room = MAX_DOCUMENTS - documents.length;

  const addFiles = async (picked: File[]) => {
    const failed = picked
      .slice(room)
      .map((file) => `${file.name}: the knowledge base holds at most ${MAX_DOCUMENTS} documents`);
    const taken = new Set(documents.map((document) => document.name.toLowerCase()));
    const added: KnowledgeBaseEntry[] = [];
    const accepted = picked.slice(0, room);
    for (const [index, file] of accepted.entries()) {
      setAdding(`Reading ${file.name} (${index + 1} of ${accepted.length})`);
      try {
        const document = await uploadDocument(file);
        added.push({ document_id: document.id, name: freeName(document.name, taken) });
      } catch (error) {
        failed.push(`${file.name}: ${(error as Error).message}`);
      }
    }
    if (added.length > 0) {
      setAdding("Saving the knowledge base");
      try {
        await save.mutateAsync((current) => [...current, ...added]);
      } catch (error) {
        failed.push((error as Error).message);
      }
    }
    if (failed.length > 0) {
      toast.error("Some documents were not added", { description: failed.join("\n") });
    }
    setAdding(null);
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

  const remove = (target: KnowledgeBaseDocument, close: () => void) =>
    save.mutate((current) => current.filter((entry) => entry.document_id !== target.document_id), {
      onSettled: close,
    });

  const addButtons = (
    <div className="flex gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={room <= 0 || busy}
        onClick={() => setOpen("new")}
      >
        <Plus />
        Add text
      </Button>
      <Button
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
    <Panel className="overflow-hidden">
      <PanelHeader title="Knowledge base" action={documents.length > 0 && addButtons} />
      <input
        ref={files}
        type="file"
        accept=".pdf,.txt,.md"
        multiple
        hidden
        onChange={(e) => {
          void addFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />

      {adding && (
        <p className="flex items-center gap-2 px-5 pt-4 text-sm text-muted-foreground">
          <Spinner />
          {adding}
        </p>
      )}

      {documents.length === 0 ? (
        <div className="grid justify-items-start gap-3 px-5 py-6">
          <p className="text-sm text-muted-foreground">
            No documents yet. Add the FAQ, policies or product facts the agent answers from, as PDF,
            TXT or MD files or pasted text. Truman reads them to write scenarios.
          </p>
          {addButtons}
        </div>
      ) : (
        <ul className="divide-y">
          {documents.map((document) => (
            <li key={document.document_id} className="flex items-center gap-3 px-5 py-3">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <button
                type="button"
                onClick={() => setOpen(document)}
                className="grid min-w-0 flex-1 gap-0.5 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                <span className="truncate text-sm font-medium">{document.name}</span>
                <span className="truncate text-xs text-muted-foreground tabular-nums">
                  {details(document)}
                </span>
                {Boolean(document.empty_pages) && (
                  <span className="text-xs text-status-warning">
                    {document.empty_pages} of {document.pages} pages had no text (scanned?)
                  </span>
                )}
              </button>
              {document.media_type && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Download ${document.name}`}
                  onClick={() => void download(document)}
                >
                  <Download />
                </Button>
              )}
              <DeleteConfirm
                name={document.name}
                description="The agent stops using it. Earlier versions of the agent keep it."
                pending={busy}
                onDelete={(close) => remove(document, close)}
              />
            </li>
          ))}
        </ul>
      )}
      {save.error && !adding && <FieldError className="px-5 pb-4">{save.error.message}</FieldError>}

      {open !== null && (
        <DocumentSheet
          key={open === "new" ? "new" : open.document_id}
          document={open === "new" ? undefined : open}
          documents={documents}
          saving={busy}
          onSave={(change) => save.mutateAsync(change)}
          onClosed={() => setOpen(null)}
        />
      )}
    </Panel>
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
  onSave: (change: (current: KnowledgeBaseEntry[]) => KnowledgeBaseEntry[]) => Promise<unknown>;
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
      const id =
        document && text === null
          ? document.document_id
          : (await createTextDocument(trimmed, shownText)).id;
      const entry = { document_id: id, name: trimmed };
      await onSave((current) =>
        document
          ? current.map((other) => (other.document_id === document.document_id ? entry : other))
          : [...current, entry],
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
        <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-4 px-4">
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
                className="h-full resize-none font-mono text-xs"
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
                <FieldDescription>
                  Edited text is saved as pasted text, and the original file is no longer linked.
                </FieldDescription>
              )
            )}
          </Field>
          {(error || loaded.error) && <FieldError>{error ?? loaded.error?.message}</FieldError>}
        </div>
        <SheetFooter className="flex-row justify-end">
          <Button variant="ghost" disabled={working} onClick={requestClose}>
            Cancel
          </Button>
          <Button
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
