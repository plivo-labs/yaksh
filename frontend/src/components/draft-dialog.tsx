import { Minus, Plus, Sparkles } from "lucide-react";
import { type ReactNode, type SubmitEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { counted } from "@/lib/format";
import { openStream, readEvents } from "@/lib/sse";
import type { DraftWords } from "@/lib/drafts";
import { type ForkRequest, MAX_FORKS } from "@/lib/types";

type Phase = "input" | "writing" | "review";

/** How the writing ended, which decides the line above the review. */
interface Ending {
  planned: number | null;
  dropped: string[];
  failed: string | null;
  stopped: boolean;
}

function reviewLine(
  words: DraftWords,
  ending: Ending,
  written: number,
  asked: number,
): string | null {
  if (ending.failed) return `Could not write the ${words.many}: ${ending.failed}`;
  if (ending.planned === 0)
    return `The instruction was not enough for any ${words.one}. Go back and say what should change.`;
  if (ending.stopped) return `Stopped. ${written} of the ${asked} ${words.many} were written.`;
  if (ending.dropped.length > 0)
    return `Could not write ${counted(ending.dropped.length, words.one, words.many)}: ${ending.dropped[0]}`;
  if (written < asked)
    return `The instruction was enough for ${written} of the ${asked} ${words.many}. ${words.verb} these, or go back and add more changes.`;
  return null;
}

/** Drafts that a model writes from an instruction: what should change and how many, then the
 * drafts as they are written, then a review where each is checked to be saved, all of them at
 * first. `save` saves the chosen drafts and calls `done` with each one's id as it is saved, so a
 * save that fails part way retries only the rest; `onSaved` then gets every id, in order. */
export function DraftDialog<T extends { name: string }>({
  words,
  originalName,
  path,
  body,
  most = MAX_FORKS,
  inputExtra,
  ready = true,
  changes,
  manual,
  save: saveDrafts,
  onSaved,
  onClosed,
}: {
  words: DraftWords;
  originalName: string;
  /** The draft endpoint, such as `/scenarios/<id>/forks/draft`. */
  path: string;
  /** More fields of the draft request. */
  body?: Record<string, unknown>;
  /** The most drafts one request may ask for. */
  most?: number;
  /** More fields under the instruction. */
  inputExtra?: ReactNode;
  /** False while inputExtra holds a choice that cannot be written. */
  ready?: boolean;
  /** What a draft changes from the original, one line each. */
  changes: (draft: T) => ReactNode[];
  manual?: { label: string; onClick: () => void };
  save: (
    chosen: { draft: T; index: number }[],
    done: (index: number, id: string) => void,
  ) => Promise<void>;
  onSaved?: (ids: string[]) => void;
  onClosed: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [phase, setPhase] = useState<Phase>("input");
  const [instruction, setInstruction] = useState("");
  const [count, setCount] = useState(Math.min(3, most));
  const [asked, setAsked] = useState(Math.min(3, most));
  const [drafts, setDrafts] = useState<T[]>([]);
  /** The forks left out of the save; every other one is saved. */
  const [unchecked, setUnchecked] = useState<ReadonlySet<number>>(new Set());
  /** The drafts already saved, with their ids, so a save that failed part way retries only
   * the rest. */
  const [saved, setSaved] = useState<ReadonlyMap<number, string>>(new Map());
  const [ending, setEnding] = useState<Ending>({
    planned: null,
    dropped: [],
    failed: null,
    stopped: false,
  });
  const [refused, setRefused] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const generate = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    setRefused(null);
    setAsked(count);
    setDrafts([]);
    setUnchecked(new Set());
    setSaved(new Map());
    setEnding({ planned: null, dropped: [], failed: null, stopped: false });
    setPhase("writing");
    let response: Response;
    try {
      response = await openStream(path, abort.signal, {
        ...body,
        instruction: text,
        count,
      } satisfies ForkRequest);
    } catch (failure) {
      controller.current = null;
      if (abort.signal.aborted) {
        setPhase("input");
        return;
      }
      setRefused(failure instanceof Error ? failure.message : String(failure));
      setPhase("input");
      return;
    }
    await readEvents(response, ({ event, data }) => {
      const payload = JSON.parse(data);
      if (event === "planned") setEnding((current) => ({ ...current, planned: payload.count }));
      else if (event === words.event) setDrafts((current) => [...current, payload as T]);
      else if (event === "dropped")
        setEnding((current) => ({ ...current, dropped: [...current.dropped, payload.reason] }));
      else if (event === "failed") setEnding((current) => ({ ...current, failed: payload.error }));
    }).catch(() =>
      setEnding((current) =>
        abort.signal.aborted
          ? { ...current, stopped: true }
          : { ...current, failed: "the connection to Yaksh was lost" },
      ),
    );
    controller.current = null;
    setPhase("review");
  };

  const back = () => {
    setDrafts([]);
    setSaveError(null);
    setPhase("input");
  };

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    const ids = new Map(saved);
    try {
      await saveDrafts(chosen, (index, id) => {
        ids.set(index, id);
        setSaved(new Map(ids));
      });
      onSaved?.([...ids.entries()].sort(([a], [b]) => a - b).map(([, id]) => id));
      setOpen(false);
    } catch (failure) {
      setSaveError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setSaving(false);
    }
  };

  const chosen = drafts
    .map((draft, index) => ({ draft, index }))
    .filter(({ index }) => !unchecked.has(index) && !saved.has(index));
  const check = (index: number, on: boolean) =>
    setUnchecked((current) => {
      const next = new Set(current);
      if (on) next.delete(index);
      else next.add(index);
      return next;
    });
  const writing = phase === "writing";
  const placeholders = Math.max(
    (ending.planned ?? asked) - drafts.length - ending.dropped.length,
    0,
  );
  const line = phase === "review" ? reviewLine(words, ending, drafts.length, asked) : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !saving && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 pt-6 pb-4">
          <DialogTitle>
            {phase === "review" ? counted(drafts.length, words.one, words.many) : words.title}
          </DialogTitle>
          <DialogDescription>
            {phase === "input" ? originalName : `Of "${originalName}".`}
          </DialogDescription>
        </DialogHeader>

        {phase === "input" ? (
          <form
            id="fork-form"
            noValidate
            onSubmit={generate}
            className="grid min-h-0 flex-1 gap-5 overflow-y-auto px-6 py-5"
          >
            <Field>
              <FieldLabel htmlFor="fork-instruction">What should change?</FieldLabel>
              <Textarea
                id="fork-instruction"
                rows={4}
                autoFocus
                maxLength={1000}
                placeholder={words.placeholder}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
              />
              {refused && <FieldError>{refused}</FieldError>}
            </Field>
            <div className="flex items-center gap-3">
              <span id="fork-count-label" className="text-s-500 first-letter:uppercase">
                {words.many}
              </span>
              <div
                role="group"
                aria-labelledby="fork-count-label"
                className="flex items-center rounded-md border"
              >
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Fewer ${words.many}`}
                  disabled={count <= 1}
                  onClick={() => setCount(count - 1)}
                >
                  <Minus />
                </Button>
                <output className="w-8 text-center text-p-400" aria-live="polite">
                  {count}
                </output>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`More ${words.many}`}
                  disabled={count >= most}
                  onClick={() => setCount(count + 1)}
                >
                  <Plus />
                </Button>
              </div>
              <span className="text-s-400 text-muted-foreground">Up to {most}</span>
            </div>
            {inputExtra}
          </form>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            {writing && (
              <div
                role="status"
                className="flex items-center gap-3 border-b bg-muted/40 px-6 py-3 text-p-400"
              >
                <Spinner />
                {ending.planned === null
                  ? "Reading the instruction."
                  : `Writing ${words.many}: ${drafts.length} of ${ending.planned} done.`}
              </div>
            )}
            {line && (
              <p
                role={ending.failed ? "alert" : "status"}
                className={
                  ending.failed
                    ? "border-b bg-destructive/5 px-6 py-3 text-p-400 text-destructive"
                    : "border-b bg-muted/40 px-6 py-3 text-p-400"
                }
              >
                {line}
              </p>
            )}
            {phase === "review" && drafts.length > 1 && (
              <label className="flex items-center gap-3 border-b px-6 py-3 text-s-500">
                <Checkbox
                  disabled={saving}
                  checked={unchecked.size === 0}
                  indeterminate={unchecked.size > 0 && unchecked.size < drafts.length}
                  onCheckedChange={(on) =>
                    setUnchecked(on ? new Set() : new Set(drafts.map((_, index) => index)))
                  }
                />
                Select all
              </label>
            )}
            <ul className="divide-y px-6">
              {drafts.map((draft, index) =>
                saved.has(index) ? null : (
                  <li key={index} className="flex items-start gap-3 py-4">
                    {phase === "review" && (
                      <Checkbox
                        className="mt-0.5"
                        disabled={saving}
                        aria-label={`Save ${draft.name}`}
                        checked={!unchecked.has(index)}
                        onCheckedChange={(on) => check(index, on)}
                      />
                    )}
                    <div className="grid min-w-0 flex-1 gap-1.5">
                      <span className="text-s-500 wrap-anywhere">{draft.name}</span>
                      {changes(draft).map((change, at) => (
                        <span key={at} className="text-s-400 text-muted-foreground">
                          {change}
                        </span>
                      ))}
                    </div>
                  </li>
                ),
              )}
              {writing &&
                Array.from({ length: placeholders }, (_, index) => (
                  <li key={`waiting-${index}`} aria-hidden className="grid gap-2 py-5">
                    <Skeleton className="h-3 w-1/2" />
                    <Skeleton className="h-2.5 w-2/3" />
                  </li>
                ))}
            </ul>
          </div>
        )}

        {saveError && <FieldError className="px-6 pb-3">{saveError}</FieldError>}

        <DialogFooter className="border-t px-6 py-4 sm:justify-between">
          {phase === "input" ? (
            <>
              {manual ? (
                <Button type="button" variant="link" className="px-0" onClick={manual.onClick}>
                  {manual.label}
                </Button>
              ) : (
                <span />
              )}
              <Button type="submit" form="fork-form" disabled={!instruction.trim() || !ready}>
                <Sparkles />
                Generate
              </Button>
            </>
          ) : writing ? (
            <>
              <span className="text-s-400 text-muted-foreground">
                Nothing is saved until you choose.
              </span>
              <Button type="button" variant="outline" onClick={() => controller.current?.abort()}>
                Stop
              </Button>
            </>
          ) : (
            <>
              <span />
              <div className="flex gap-2">
                <Button type="button" variant="outline" disabled={saving} onClick={back}>
                  Back
                </Button>
                {drafts.length > 0 && (
                  <Button
                    type="button"
                    disabled={saving || chosen.length === 0}
                    onClick={() => void save()}
                  >
                    {saving && <Spinner />}
                    {words.verb} {counted(chosen.length, words.one, words.many)}
                  </Button>
                )}
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
