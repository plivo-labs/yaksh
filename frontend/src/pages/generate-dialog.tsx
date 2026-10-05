import { type SubmitEvent, useState } from "react";

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
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { revealErrors } from "@/lib/forms";
import { APPEAR } from "@/lib/motion";
import { usePersonas } from "@/lib/queries";
import { type Agent, type GenerateInput, type GenerationMode, MAX_GENERATED } from "@/lib/types";

const MODES: { value: GenerationMode; label: string; hint: string }[] = [
  {
    value: "agent",
    label: "What the agent does",
    hint: "Scenarios for the agent's jobs and refusals, from its brief, config and knowledge base.",
  },
  {
    value: "knowledge_base",
    label: "Knowledge base questions",
    hint: "Questions a caller could ask that the chosen documents answer, and some they do not.",
  },
];

export function GenerateDialog({
  agent,
  onStart,
  onClosed,
}: {
  agent: Agent;
  onStart: (input: GenerateInput) => Promise<void>;
  onClosed: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [mode, setMode] = useState<GenerationMode>("agent");
  const [count, setCount] = useState("5");
  const [instructions, setInstructions] = useState("");
  const [documentIds, setDocumentIds] = useState(() =>
    agent.knowledge_base.map((entry) => entry.document_id),
  );
  /** Null until the user changes the choice: then the first persona is checked. */
  const [checkedPersonas, setCheckedPersonas] = useState<ReadonlySet<string> | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const personas = usePersonas();
  const personaList = personas.data ?? [];
  const checked = checkedPersonas ?? new Set(personaList.slice(0, 1).map((persona) => persona.id));
  const personaIds = personaList
    .filter((persona) => checked.has(persona.id))
    .map((persona) => persona.id);
  const personasValid = personaIds.length > 0 && personaIds.length <= MAX_GENERATED;

  const number = Number(count);
  const countValid = Number.isInteger(number) && number >= 1 && number <= MAX_GENERATED;
  const knowledgeBase = mode === "knowledge_base";
  const documentsValid = !knowledgeBase || documentIds.length > 0;
  const hasDocuments = agent.knowledge_base.length > 0;

  const togglePersona = (id: string, on: boolean) => {
    const next = new Set(checked);
    if (on) next.add(id);
    else next.delete(id);
    setCheckedPersonas(next);
  };

  const toggleDocument = (id: string, on: boolean) =>
    setDocumentIds((current) =>
      on ? [...current, id] : current.filter((documentId) => documentId !== id),
    );

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valid = countValid && documentsValid && personasValid;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    setPending(true);
    setError(null);
    try {
      await onStart({
        mode,
        count: number,
        instructions: instructions.trim(),
        document_ids: knowledgeBase ? documentIds : [],
        persona_ids: personaIds,
      });
      setOpen(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !pending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>Generate scenarios</DialogTitle>
          <DialogDescription>
            Truman saves each scenario as it is written. Delete the ones you do not want.
          </DialogDescription>
        </DialogHeader>

        <form
          id="generate-form"
          noValidate
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 py-1"
        >
          <FieldGroup className="pb-6">
            <Field>
              <FieldLabel htmlFor="generate-mode">Test</FieldLabel>
              <Select
                items={MODES}
                value={mode}
                onValueChange={(value) => value && setMode(value as GenerationMode)}
              >
                <SelectTrigger id="generate-mode" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {MODES.map((item) => (
                      <SelectItem
                        key={item.value}
                        value={item.value}
                        disabled={item.value === "knowledge_base" && !hasDocuments}
                      >
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                {MODES.find((item) => item.value === mode)?.hint}
                {!hasDocuments && " Add knowledge base documents to test answers from them."}
              </FieldDescription>
            </Field>

            {knowledgeBase && (
              <FieldSet className={APPEAR}>
                <FieldLegend variant="label">Documents</FieldLegend>
                <ul className="grid gap-2">
                  {agent.knowledge_base.map((entry) => (
                    <li key={entry.document_id} className="flex items-center gap-3">
                      <Checkbox
                        id={`generate-document-${entry.document_id}`}
                        checked={documentIds.includes(entry.document_id)}
                        onCheckedChange={(on) => toggleDocument(entry.document_id, on)}
                      />
                      <label
                        htmlFor={`generate-document-${entry.document_id}`}
                        className="min-w-0 flex-1 truncate text-p-400"
                      >
                        {entry.name}
                      </label>
                    </li>
                  ))}
                </ul>
                {submitted && !documentsValid && (
                  <FieldError>Pick at least one document.</FieldError>
                )}
              </FieldSet>
            )}

            <FieldSet>
              <FieldLegend variant="label">Personas</FieldLegend>
              <FieldDescription>
                A job or question gets a checked persona again only after it got all of them.
              </FieldDescription>
              {personas.isPending && (
                <p className="text-p-400 text-muted-foreground">Loading personas</p>
              )}
              {personas.isError && (
                <FieldError>Could not load the personas: {personas.error.message}</FieldError>
              )}
              <ul className="grid gap-2">
                {personaList.map((persona) => (
                  <li key={persona.id} className="flex items-center gap-3">
                    <Checkbox
                      id={`generate-persona-${persona.id}`}
                      checked={checked.has(persona.id)}
                      onCheckedChange={(on) => togglePersona(persona.id, on)}
                    />
                    <label
                      htmlFor={`generate-persona-${persona.id}`}
                      className="min-w-0 flex-1 truncate text-p-400"
                    >
                      {persona.name}
                    </label>
                  </li>
                ))}
              </ul>
              {submitted && personas.isSuccess && !personasValid && (
                <FieldError>
                  {personaList.length === 0
                    ? "Create a persona first."
                    : personaIds.length === 0
                      ? "Pick at least one persona."
                      : `Pick at most ${MAX_GENERATED} personas.`}
                </FieldError>
              )}
            </FieldSet>

            <Field>
              <FieldLabel htmlFor="generate-count">Number of scenarios</FieldLabel>
              <Input
                id="generate-count"
                type="number"
                inputMode="numeric"
                min={1}
                max={MAX_GENERATED}
                aria-invalid={submitted && !countValid}
                className="w-24"
                value={count}
                onChange={(e) => setCount(e.target.value)}
              />
              <FieldDescription>
                Up to {MAX_GENERATED}. A short brief can give fewer, so no two are the same.
              </FieldDescription>
              {submitted && !countValid && (
                <FieldError>Enter a whole number from 1 to {MAX_GENERATED}.</FieldError>
              )}
            </Field>

            <Field>
              <FieldLabel htmlFor="generate-instructions">Instructions</FieldLabel>
              <Textarea
                id="generate-instructions"
                rows={3}
                maxLength={2000}
                placeholder="Focus on rescheduling. Include callers who give a wrong date of birth."
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
              />
              <FieldDescription>Optional.</FieldDescription>
            </Field>
          </FieldGroup>
        </form>

        {error && <FieldError className="px-6 pb-3">{error}</FieldError>}

        <DialogFooter className="border-t px-6 py-4">
          <Button type="button" variant="ghost" disabled={pending} onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button type="submit" form="generate-form" disabled={pending}>
            {pending && <Spinner />}
            Generate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
