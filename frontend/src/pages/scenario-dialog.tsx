import { Plus, X } from "lucide-react";
import { type SubmitEvent, useState } from "react";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
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
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useCloseGuard } from "@/hooks/use-close-guard";
import { useDeleteScenario, useSaveScenario } from "@/lib/queries";
import type { Fact, Scenario, ScenarioInput } from "@/lib/types";

const APPEAR = "transition-opacity duration-150 ease-out starting:opacity-0";

const EMPTY: ScenarioInput = {
  name: "",
  goal: "",
  known_facts: [],
  unknown_facts: [],
  criteria: [""],
};

function toDraft(scenario: Scenario): ScenarioInput {
  return {
    name: scenario.name,
    goal: scenario.goal,
    known_facts: scenario.known_facts,
    unknown_facts: scenario.unknown_facts,
    criteria: scenario.criteria,
  };
}

/** The draft as the API takes it: text trimmed, rows left fully empty dropped. */
function toInput(draft: ScenarioInput): ScenarioInput {
  return {
    name: draft.name.trim(),
    goal: draft.goal.trim(),
    known_facts: draft.known_facts
      .map((fact) => ({ name: fact.name.trim(), value: fact.value.trim() }))
      .filter((fact) => fact.name || fact.value),
    unknown_facts: draft.unknown_facts.map((name) => name.trim()).filter(Boolean),
    criteria: draft.criteria.map((text) => text.trim()).filter(Boolean),
  };
}

function AddRow({
  count,
  limit,
  onAdd,
  children,
}: {
  count: number;
  limit: number;
  onAdd: () => void;
  children: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <Button type="button" variant="outline" size="sm" disabled={count >= limit} onClick={onAdd}>
        <Plus />
        {children}
      </Button>
      {count >= limit && (
        <span className="text-sm text-muted-foreground">The limit is {limit}.</span>
      )}
    </div>
  );
}

export function ScenarioDialog({
  agentId,
  scenario,
  onSaved,
  onClosed,
}: {
  agentId: string;
  scenario?: Scenario;
  onSaved?: (scenario: Scenario) => void;
  onClosed: () => void;
}) {
  const id = scenario?.id;
  const save = useSaveScenario(agentId, id);
  const remove = useDeleteScenario(agentId);
  const [initial] = useState<ScenarioInput>(() => (scenario ? toDraft(scenario) : EMPTY));
  const [draft, setDraft] = useState<ScenarioInput>(initial);
  const [submitted, setSubmitted] = useState(false);
  const guard = useCloseGuard(JSON.stringify(toInput(draft)) !== JSON.stringify(toInput(initial)));

  const change = (next: (current: ScenarioInput) => Partial<ScenarioInput>) => {
    save.reset();
    setDraft((current) => ({ ...current, ...next(current) }));
  };
  const setFact = (index: number, next: Partial<Fact>) =>
    change((current) => ({
      known_facts: current.known_facts.map((fact, at) =>
        at === index ? { ...fact, ...next } : fact,
      ),
    }));
  const addFact = () =>
    change((current) => ({ known_facts: [...current.known_facts, { name: "", value: "" }] }));
  const removeFact = (index: number) =>
    change((current) => ({ known_facts: current.known_facts.filter((_, at) => at !== index) }));
  const addListItem = (key: "unknown_facts" | "criteria") =>
    change((current) => ({ [key]: [...current[key], ""] }));
  const setListItem = (key: "unknown_facts" | "criteria", index: number, value: string) =>
    change((current) => ({ [key]: current[key].map((item, at) => (at === index ? value : item)) }));
  const removeListItem = (key: "unknown_facts" | "criteria", index: number) =>
    change((current) => ({ [key]: current[key].filter((_, at) => at !== index) }));

  const input = toInput(draft);
  const halfFact = input.known_facts.some((fact) => !fact.name || !fact.value);

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!input.name || !input.goal || input.criteria.length === 0 || halfFact) return;
    save.mutate(input, {
      onSuccess: (saved) => {
        onSaved?.(saved);
        guard.close();
      },
    });
  };

  return (
    <Dialog
      open={guard.open}
      onOpenChange={(next) => !next && guard.requestClose()}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-2xl">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>{id ? "Edit scenario" : "New scenario"}</DialogTitle>
        </DialogHeader>

        <form
          id="scenario-form"
          noValidate
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 py-1"
        >
          <FieldGroup className="pb-6">
            <Field>
              <FieldLabel htmlFor="scenario-name">Name</FieldLabel>
              <Input
                id="scenario-name"
                required
                aria-invalid={submitted && !input.name}
                maxLength={80}
                value={draft.name}
                onChange={(e) => change(() => ({ name: e.target.value }))}
              />
              {submitted && !input.name && (
                <FieldError className={APPEAR}>Enter a name.</FieldError>
              )}
            </Field>

            <Field>
              <FieldLabel htmlFor="scenario-goal">Goal</FieldLabel>
              <Textarea
                id="scenario-goal"
                required
                aria-invalid={submitted && !input.goal}
                rows={4}
                maxLength={2000}
                placeholder="Move your cleaning to an evening next week. If there is none, keep your current appointment."
                value={draft.goal}
                onChange={(e) => change(() => ({ goal: e.target.value }))}
              />
              <FieldDescription>Put names, numbers and dates in the facts below.</FieldDescription>
              {submitted && !input.goal && (
                <FieldError className={APPEAR}>Describe what the caller wants.</FieldError>
              )}
            </Field>

            <FieldSet>
              <FieldLegend variant="label">What the caller knows</FieldLegend>
              <FieldDescription>
                Write dates relative to today, for example next Thursday.
              </FieldDescription>
              <div className="grid gap-2">
                {draft.known_facts.map((fact, index) => (
                  <div key={index} className="flex items-start gap-2">
                    <div className="flex flex-1 flex-col gap-2 sm:flex-row">
                      <Input
                        aria-label={`Fact ${index + 1} name`}
                        aria-invalid={submitted && !fact.name.trim() && Boolean(fact.value.trim())}
                        placeholder="Name"
                        maxLength={80}
                        className="sm:w-2/5"
                        value={fact.name}
                        onChange={(e) => setFact(index, { name: e.target.value })}
                      />
                      <Input
                        aria-label={`Fact ${index + 1} value`}
                        aria-invalid={submitted && !fact.value.trim() && Boolean(fact.name.trim())}
                        placeholder="Value"
                        maxLength={500}
                        className="sm:flex-1"
                        value={fact.value}
                        onChange={(e) => setFact(index, { value: e.target.value })}
                      />
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove fact ${index + 1}`}
                      onClick={() => removeFact(index)}
                    >
                      <X />
                    </Button>
                  </div>
                ))}
              </div>
              {submitted && halfFact && (
                <FieldError className={APPEAR}>Give each fact a name and a value.</FieldError>
              )}
              <AddRow count={draft.known_facts.length} limit={30} onAdd={addFact}>
                Add fact
              </AddRow>
            </FieldSet>

            <FieldSet>
              <FieldLegend variant="label">What the caller does not have</FieldLegend>
              <div className="grid gap-2">
                {draft.unknown_facts.map((name, index) => (
                  <div key={index} className="flex gap-2">
                    <Input
                      aria-label={`Unknown fact ${index + 1}`}
                      placeholder="Patient ID"
                      maxLength={80}
                      className="flex-1"
                      value={name}
                      onChange={(e) => setListItem("unknown_facts", index, e.target.value)}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove unknown fact ${index + 1}`}
                      onClick={() => removeListItem("unknown_facts", index)}
                    >
                      <X />
                    </Button>
                  </div>
                ))}
              </div>
              <AddRow
                count={draft.unknown_facts.length}
                limit={20}
                onAdd={() => addListItem("unknown_facts")}
              >
                Add missing fact
              </AddRow>
            </FieldSet>

            <FieldSet>
              <FieldLegend variant="label">Criteria</FieldLegend>
              <FieldDescription>
                The caller never sees these. Write what the agent must say or do on the call.
              </FieldDescription>
              <div className="grid gap-2">
                {draft.criteria.map((text, index) => (
                  <div key={index} className="flex gap-2">
                    <Textarea
                      aria-label={`Criterion ${index + 1}`}
                      rows={2}
                      maxLength={500}
                      placeholder="Reads the new date and time back before it moves the appointment."
                      className="flex-1"
                      value={text}
                      onChange={(e) => setListItem("criteria", index, e.target.value)}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove criterion ${index + 1}`}
                      onClick={() => removeListItem("criteria", index)}
                    >
                      <X />
                    </Button>
                  </div>
                ))}
              </div>
              {submitted && input.criteria.length === 0 && (
                <FieldError className={APPEAR}>Add at least one criterion.</FieldError>
              )}
              <AddRow
                count={draft.criteria.length}
                limit={10}
                onAdd={() => addListItem("criteria")}
              >
                Add criterion
              </AddRow>
            </FieldSet>
          </FieldGroup>
        </form>

        {(save.error || remove.error) && (
          <FieldError className={`px-6 pb-3 ${APPEAR}`}>
            {(save.error ?? remove.error)?.message}
          </FieldError>
        )}

        <DialogFooter className="border-t px-6 py-4">
          {id && (
            <DeleteConfirm
              name={initial.name}
              description="Past and queued conversations are not changed."
              pending={remove.isPending}
              onDelete={(close) => remove.mutate(id, { onSuccess: guard.close, onSettled: close })}
            />
          )}
          <Button type="button" variant="ghost" onClick={guard.requestClose}>
            Cancel
          </Button>
          <Button type="submit" form="scenario-form" disabled={save.isPending}>
            {save.isPending && <Spinner />}
            {id ? "Save changes" : "Create scenario"}
          </Button>
        </DialogFooter>

        <DiscardConfirm subject="scenario" {...guard.discard} />
      </DialogContent>
    </Dialog>
  );
}
