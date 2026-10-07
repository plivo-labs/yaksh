import { ArrowLeft, FileJson, TriangleAlert, Upload } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { Panel } from "@/components/panel";
import { StepFooter } from "@/components/step-footer";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { useFileDrop } from "@/hooks/use-file-drop";
import { ApiError } from "@/lib/api";
import { textSize } from "@/lib/format";
import { startImportedDraft } from "@/lib/new-agent-draft";
import { randomKey } from "@/lib/random-key";
import { draftBrief, keys, useImportAgentFile } from "@/lib/queries";
import { LANGUAGE_NAMES } from "@/lib/types";

/** The API takes up to a million characters; a character is at most four bytes of UTF-8, so a
 * larger file cannot fit and is not read. */
const MAX_FILE_BYTES = 4_000_000;

/** Reads an agent file into a draft, then opens the new-agent wizard with the draft filled. */
export function AgentImportJsonPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const picker = useRef<HTMLInputElement>(null);
  /** The chosen file; `content` is null until the browser has read it. `briefDraftId` names
   * the brief Yaksha starts to draft as soon as it has the text, so it is ready sooner. */
  const [file, setFile] = useState<{
    name: string;
    content: string | null;
    briefDraftId: string | null;
  } | null>(null);
  /** A problem found before the file reaches the API. */
  const [problem, setProblem] = useState<string | null>(null);
  /** Counts choices, so a file chosen earlier and read later does not replace a newer one. */
  const choice = useRef(0);
  const read = useImportAgentFile();
  const unrecognized = read.error instanceof ApiError && read.error.code === "not_recognized";
  const reading = read.isPending || (file !== null && file.content === null && problem === null);

  const choose = async (picked: File[]) => {
    const chosen = picked[0];
    if (!chosen) return;
    const id = ++choice.current;
    read.reset();
    setProblem(null);
    setFile({ name: chosen.name, content: null, briefDraftId: null });
    if (chosen.size > MAX_FILE_BYTES) {
      setProblem("The file is larger than a config can be: 1,000,000 characters.");
      return;
    }
    let content: string;
    try {
      content = await chosen.text();
    } catch {
      if (id === choice.current)
        setProblem("The browser could not read the file. Choose it again.");
      return;
    }
    if (id !== choice.current) return;
    const briefDraftId = randomKey();
    void client.prefetchQuery({
      queryKey: keys.briefDraft(briefDraftId),
      queryFn: () => draftBrief(content),
      staleTime: Infinity,
      retry: false,
    });
    setFile({ name: chosen.name, content, briefDraftId });
    read.mutate(content);
  };
  const drop = useFileDrop((picked) => void choose(picked));

  const open = (recognized: boolean) => {
    if (file?.content == null || file.briefDraftId === null) return;
    const draft = read.data;
    const started = startImportedDraft(
      recognized && draft
        ? {
            name: draft.name ?? "",
            external_id: draft.external_id ?? "",
            language: draft.language,
            config: draft.config,
          }
        : { config: file.content },
      { file: file.name, recognized },
      file.briefDraftId,
    );
    if (started) navigate("/agents/new/details?step=1");
    else
      setProblem(
        "The browser blocks the storage that takes the file to the next step. Allow site data for Yaksha, then try again.",
      );
  };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6">
      <div className="grid gap-1">
        <h1 className="text-h3-500">Import from a JSON file</h1>
        <p className="text-p-400 text-muted-foreground">
          Yaksha reads a Plivo CX agent download. ElevenLabs, Vapi and Retell files are coming soon.
        </p>
      </div>
      <input
        ref={picker}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(e) => {
          void choose(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />

      <Panel className="relative grid gap-4 px-5 py-5" {...drop.target}>
        {file ? (
          <div className="flex items-center gap-3 rounded-md border px-4 py-3">
            <FileJson aria-hidden className="size-4.5 shrink-0 text-muted-foreground" />
            <div className="grid min-w-0 flex-1">
              <span className="truncate text-p-500">{file.name}</span>
              {file.content !== null && (
                <span className="text-s-400 text-muted-foreground">
                  {textSize(file.content.length)}
                </span>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={() => picker.current?.click()}>
              Choose another file
            </Button>
          </div>
        ) : (
          <div className="grid justify-items-center gap-4 rounded-lg border border-dashed px-6 py-10 text-center">
            <span className="grid size-10 place-items-center rounded-full bg-muted text-muted-foreground">
              <Upload className="size-4.5" />
            </span>
            <div className="grid gap-1">
              <p className="text-p-500">Drop a .json file here</p>
              <p className="text-p-400 text-muted-foreground">
                The Plivo CX console downloads it as {"{name}"}-config.json.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => picker.current?.click()}>
              Choose a file
            </Button>
          </div>
        )}

        {problem && <FieldError>{problem}</FieldError>}
        <p role="status" className="sr-only">
          {read.data ? "Yaksha read the file. Import is ready." : ""}
        </p>
        {reading && (
          <p className="flex items-center gap-2 text-p-400 text-muted-foreground">
            <Spinner />
            Reading the file
          </p>
        )}
        {read.data && (
          <div className="grid gap-3">
            <p className="text-p-400">A Plivo CX agent download. Yaksha fills in:</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-p-400">
              <dt className="text-muted-foreground">Name</dt>
              <dd>{read.data.name ?? "Not in the file"}</dd>
              <dt className="text-muted-foreground">Agent ID</dt>
              <dd className="truncate">{read.data.external_id ?? "Not in the file"}</dd>
              <dt className="text-muted-foreground">Language</dt>
              <dd>{LANGUAGE_NAMES[read.data.language]}</dd>
              <dt className="text-muted-foreground">Config</dt>
              <dd>The whole file</dd>
            </dl>
            <p className="text-p-400 text-muted-foreground">
              You add the brief, the phone number, the knowledge base and the rules.
            </p>
          </div>
        )}
        {unrecognized && (
          <div
            role="alert"
            className="grid grid-cols-[auto_1fr] gap-x-2.5 gap-y-1 rounded-md bg-warning px-4 py-3 text-warning-foreground"
          >
            <TriangleAlert aria-hidden className="mt-0.5 size-4" />
            <p className="text-p-500">Yaksha does not know this format</p>
            <p className="col-start-2 text-p-400">
              It is not an agent file that Yaksha reads. You can still use the whole file as the
              agent's config, and fill in the rest yourself.
            </p>
            <div className="col-start-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => open(false)}>
                Use it as the config
              </Button>
            </div>
          </div>
        )}
        {read.error && !unrecognized && <FieldError>{read.error.message}</FieldError>}

        {drop.dragging && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-lg border-2 border-dashed border-primary/40 bg-background/85"
          >
            <p className="flex items-center gap-2 text-p-500">
              <Upload className="size-4" />
              Drop to read the file
            </p>
          </div>
        )}
      </Panel>

      <StepFooter>
        <Button variant="ghost" nativeButton={false} render={<Link to="/agents/new" />}>
          <ArrowLeft />
          Back
        </Button>
        <Button className="ml-auto" disabled={!read.data} onClick={() => open(true)}>
          Import
        </Button>
      </StepFooter>
    </div>
  );
}
