import { Plus, X } from "lucide-react";
import { type SubmitEvent, useState } from "react";
import { toast } from "sonner";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { Fact } from "@/components/panel";
import { PersonaSelect } from "@/components/persona-select";
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
import { useCloseGuard } from "@/hooks/use-close-guard";
import { revealErrors } from "@/lib/forms";
import { useDefaults, useDeleteScenario, usePersonas, useSaveScenario } from "@/lib/queries";
import {
  type AgentSummary,
  CATEGORY_ITEMS,
  type Category,
  type Fact as ScenarioFact,
  type Scenario,
  type ScenarioInput,
} from "@/lib/types";

const EMPTY: ScenarioInput = {
  name: "",
  category: "happy_path",
  description: null,
  persona_id: "",
  instructions: "",
  known_facts: [],
  unknown_facts: [],
  criteria: [""],
  agent_data: [],
  first_words: null,
};

function toDraft(scenario: Scenario): ScenarioInput {
  return {
    name: scenario.name,
    category: scenario.category,
    description: scenario.description,
    persona_id: scenario.persona_id,
    instructions: scenario.instructions,
    known_facts: scenario.known_facts,
    unknown_facts: scenario.unknown_facts,
    criteria: scenario.criteria,
    agent_data: scenario.agent_data,
    first_words: scenario.first_words,
  };
}

function trimFacts(facts: ScenarioFact[]): ScenarioFact[] {
  return facts
    .map((fact) => ({ name: fact.name.trim(), value: fact.value.trim() }))
    .filter((fact) => fact.name || fact.value);
}

/** The draft as the API takes it: text trimmed, rows left fully empty dropped. */
function toInput(draft: ScenarioInput): ScenarioInput {
  return {
    name: draft.name.trim(),
    category: draft.category,
    description: draft.description?.trim() || null,
    persona_id: draft.persona_id,
    instructions: draft.instructions.trim(),
    known_facts: trimFacts(draft.known_facts),
    unknown_facts: draft.unknown_facts.map((name) => name.trim()).filter(Boolean),
    criteria: draft.criteria.map((text) => text.trim()).filter(Boolean),
    agent_data: trimFacts(draft.agent_data),
    first_words: draft.first_words?.trim() || null,
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
        <span className="text-p-400 text-muted-foreground">The limit is {limit}.</span>
      )}
    </div>
  );
}

type FactKey = "known_facts" | "agent_data";

function FactRows({
  label,
  facts,
  submitted,
  onChange,
}: {
  label: string;
  facts: ScenarioFact[];
  submitted: boolean;
  onChange: (facts: ScenarioFact[]) => void;
}) {
  const set = (index: number, next: Partial<ScenarioFact>) =>
    onChange(facts.map((fact, at) => (at === index ? { ...fact, ...next } : fact)));

  return (
    <>
      <div className="grid gap-2">
        {facts.map((fact, index) => (
          <div key={index} className="flex items-start gap-2">
            <div className="flex flex-1 flex-col gap-2 sm:flex-row">
              <Input
                aria-label={`${label} ${index + 1} name`}
                aria-invalid={submitted && !fact.name.trim() && Boolean(fact.value.trim())}
                placeholder="Name"
                maxLength={80}
                className="sm:w-2/5"
                value={fact.name}
                onChange={(e) => set(index, { name: e.target.value })}
              />
              <Input
                aria-label={`${label} ${index + 1} value`}
                aria-invalid={submitted && !fact.value.trim() && Boolean(fact.name.trim())}
                placeholder="Value"
                maxLength={500}
                className="sm:flex-1"
                value={fact.value}
                onChange={(e) => set(index, { value: e.target.value })}
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove ${label.toLowerCase()} ${index + 1}`}
              onClick={() => onChange(facts.filter((_, at) => at !== index))}
            >
              <X />
            </Button>
          </div>
        ))}
      </div>
      <AddRow
        count={facts.length}
        limit={30}
        onAdd={() => onChange([...facts, { name: "", value: "" }])}
      >
        {`Add ${label.toLowerCase()}`}
      </AddRow>
    </>
  );
}

export function ScenarioDialog({
  agent,
  scenario,
  onSaved,
  onClosed,
}: {
  agent: AgentSummary;
  scenario?: Scenario;
  onSaved?: (scenario: Scenario) => void;
  onClosed: () => void;
}) {
  const id = scenario?.id;
  const save = useSaveScenario(agent.id, id);
  const remove = useDeleteScenario(agent.id);
  const [initial] = useState<ScenarioInput>(() => (scenario ? toDraft(scenario) : EMPTY));
  const [draft, setDraft] = useState<ScenarioInput>(initial);
  const [submitted, setSubmitted] = useState(false);
  const personas = usePersonas();
  /** A new scenario shows the first persona; both sides of the change check see the same one. */
  const withPersona = (value: ScenarioInput): ScenarioInput => ({
    ...value,
    persona_id: value.persona_id || personas.data?.[0]?.id || "",
  });
  const input = toInput(withPersona(draft));
  const guard = useCloseGuard(
    JSON.stringify(input) !== JSON.stringify(toInput(withPersona(initial))),
  );

  const change = (next: (current: ScenarioInput) => Partial<ScenarioInput>) => {
    save.reset();
    setDraft((current) => ({ ...current, ...next(current) }));
  };
  const setFacts = (key: FactKey, facts: ScenarioFact[]) => change(() => ({ [key]: facts }));
  const addListItem = (key: "unknown_facts" | "criteria") =>
    change((current) => ({ [key]: [...current[key], ""] }));
  const setListItem = (key: "unknown_facts" | "criteria", index: number, value: string) =>
    change((current) => ({ [key]: current[key].map((item, at) => (at === index ? value : item)) }));
  const removeListItem = (key: "unknown_facts" | "criteria", index: number) =>
    change((current) => ({ [key]: current[key].filter((_, at) => at !== index) }));

  const defaults = useDefaults();
  const persona = personas.data?.find((item) => item.id === input.persona_id);
  const opening = persona ? defaults.data?.first_words[persona.language] : undefined;
  const outbound = agent.direction === "outbound";
  const halfFact = (facts: ScenarioFact[]) => facts.some((fact) => !fact.name || !fact.value);
  const halfKnown = halfFact(input.known_facts);
  const halfAgentData = outbound && halfFact(input.agent_data);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valid =
      Boolean(input.name) &&
      Boolean(input.persona_id) &&
      Boolean(input.instructions) &&
      input.criteria.length > 0 &&
      !halfKnown &&
      !halfAgentData;
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), valid)) return;
    save.mutate(input, {
      onSuccess: (saved) => {
        toast.success(id ? "Scenario saved" : `Added ${saved.name}`);
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
            {id && (
              <dl>
                <Fact label="Scenario id">
                  <CopyId id={id} label="scenario id" />
                </Fact>
              </dl>
            )}
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
              {submitted && !input.name && <FieldError>Enter a name.</FieldError>}
            </Field>

            <Field>
              <FieldLabel htmlFor="scenario-category">Category</FieldLabel>
              <Select
                items={CATEGORY_ITEMS}
                value={draft.category}
                onValueChange={(value) => value && change(() => ({ category: value as Category }))}
              >
                <SelectTrigger id="scenario-category" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {CATEGORY_ITEMS.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                {CATEGORY_ITEMS.find((item) => item.value === draft.category)?.hint}.
              </FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="scenario-persona">Persona</FieldLabel>
              <PersonaSelect
                id="scenario-persona"
                value={input.persona_id}
                onValueChange={(value) => change(() => ({ persona_id: value }))}
                invalid={submitted && !input.persona_id}
              />
              <FieldDescription>How the caller talks: style, language and voice.</FieldDescription>
              {submitted && personas.data?.length === 0 && (
                <FieldError>Create a persona first.</FieldError>
              )}
            </Field>

            <Field>
              <FieldLabel htmlFor="scenario-description">Description</FieldLabel>
              <Textarea
                id="scenario-description"
                rows={2}
                maxLength={500}
                placeholder="What this scenario tests and why."
                value={draft.description ?? ""}
                onChange={(e) => change(() => ({ description: e.target.value }))}
              />
              <FieldDescription>Optional. The caller never sees it.</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="scenario-instructions">Instructions</FieldLabel>
              <Textarea
                id="scenario-instructions"
                required
                aria-invalid={submitted && !input.instructions}
                rows={6}
                maxLength={4000}
                placeholder="You want to move your cleaning to an evening next week. When the agent asks for your details, give your name and date of birth. If no evening is free, keep your current appointment. Once the agent confirms, say goodbye."
                value={draft.instructions}
                onChange={(e) => change(() => ({ instructions: e.target.value }))}
              />
              <FieldDescription>
                What the caller wants and how it reacts to the agent, written to the caller as
                “you”. Put names, numbers and dates in the facts below, and mood in the persona.
              </FieldDescription>
              {submitted && !input.instructions && (
                <FieldError>Tell the caller what to do on this call.</FieldError>
              )}
            </Field>

            <Field>
              <FieldLabel htmlFor="scenario-first-words">First words</FieldLabel>
              <Input
                id="scenario-first-words"
                maxLength={200}
                placeholder={opening}
                value={draft.first_words ?? ""}
                onChange={(e) => change(() => ({ first_words: e.target.value }))}
              />
              <FieldDescription>
                What the caller says when it speaks first: when the agent waits for the caller, or
                says nothing at the start. Leave it empty for the default of the persona's language.
              </FieldDescription>
            </Field>

            <FieldSet>
              <FieldLegend variant="label">What the caller knows</FieldLegend>
              <FieldDescription>
                Write dates relative to today, for example next Thursday.
              </FieldDescription>
              <FactRows
                label="Fact"
                facts={draft.known_facts}
                submitted={submitted}
                onChange={(facts) => setFacts("known_facts", facts)}
              />
              {submitted && halfKnown && (
                <FieldError>Give each fact a name and a value.</FieldError>
              )}
            </FieldSet>

            {outbound && (
              <FieldSet>
                <FieldLegend variant="label">Data sent to the agent</FieldLegend>
                <FieldDescription>
                  Yaksha puts these in the request that starts the call, as{" "}
                  <code>{"{{agent_data.<name>}}"}</code>. The caller does not see them.
                </FieldDescription>
                <FactRows
                  label="Agent data"
                  facts={draft.agent_data}
                  submitted={submitted}
                  onChange={(facts) => setFacts("agent_data", facts)}
                />
                {submitted && halfAgentData && (
                  <FieldError>Give each item a name and a value.</FieldError>
                )}
              </FieldSet>
            )}

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
                <FieldError>Add at least one criterion.</FieldError>
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
          <FieldError className="px-6 pb-3">{(save.error ?? remove.error)?.message}</FieldError>
        )}

        <DialogFooter className="border-t px-6 py-4">
          {id && (
            <DeleteConfirm
              name={initial.name}
              description="Past and queued conversations are not changed."
              pending={remove.isPending}
              onDelete={(close) =>
                remove.mutate(id, {
                  onSuccess: () => {
                    toast.success(`Deleted ${initial.name}`);
                    guard.close();
                  },
                  onSettled: close,
                })
              }
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
