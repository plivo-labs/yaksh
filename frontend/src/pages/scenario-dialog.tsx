import { Plus, X } from "lucide-react";
import { type SubmitEvent, useState } from "react";
import { toast } from "sonner";

import { DeleteConfirm, DiscardConfirm } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { ForkedFrom } from "@/components/forked-from";
import { EffortSelect } from "@/components/effort-select";
import { ModelCombobox } from "@/components/model-combobox";
import { Fact } from "@/components/panel";
import { PersonaSelect } from "@/components/persona-select";
import { Button } from "@/components/ui/button";
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
import { useCloseGuard } from "@/hooks/use-close-guard";
import { revealErrors } from "@/lib/forms";
import {
  useDefaults,
  useDeleteScenario,
  usePersonas,
  useSaveScenario,
  useSettings,
} from "@/lib/queries";
import {
  dataSetsProblem,
  defaultDataSetName,
  fixedValues,
  trimmedDataSets,
  unknownPlaceholders,
  withPlaceholder,
} from "@/lib/data-sets";
import { cn } from "@/lib/utils";
import {
  type AgentSummary,
  CATEGORY_ITEMS,
  type CallerModel,
  type Category,
  MAX_DATA_SETS,
  type Scenario,
  type ScenarioInput,
} from "@/lib/types";
import { DataSetsGrid } from "@/pages/data-sets-grid";
import { sendsAgentData } from "@/lib/agent-draft";

const EMPTY: ScenarioInput = {
  name: "",
  category: "happy_path",
  description: null,
  persona_id: "",
  instructions: "",
  unknown_facts: [],
  criteria: [""],
  data_sets: [{ name: defaultDataSetName(1), known_facts: [], agent_data: [] }],
  first_words: null,
  caller: null,
};

function toDraft(scenario: Scenario): ScenarioInput {
  return {
    name: scenario.name,
    category: scenario.category,
    description: scenario.description,
    persona_id: scenario.persona_id,
    instructions: scenario.instructions,
    unknown_facts: scenario.unknown_facts,
    criteria: scenario.criteria,
    data_sets: scenario.data_sets,
    first_words: scenario.first_words,
    caller: scenario.caller,
  };
}

/** The draft as the API takes it: text trimmed, rows left fully empty dropped. */
function toInput(draft: ScenarioInput): ScenarioInput {
  return {
    name: draft.name.trim(),
    category: draft.category,
    description: draft.description?.trim() || null,
    persona_id: draft.persona_id,
    instructions: draft.instructions.trim(),
    unknown_facts: draft.unknown_facts.map((name) => name.trim()).filter(Boolean),
    criteria: draft.criteria.map((text) => text.trim()).filter(Boolean),
    data_sets: trimmedDataSets(draft.data_sets),
    first_words: draft.first_words?.trim() || null,
    caller: draft.caller,
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
  const settings = useSettings();
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
  const addListItem = (key: "unknown_facts" | "criteria") =>
    change((current) => ({ [key]: [...current[key], ""] }));
  const setListItem = (key: "unknown_facts" | "criteria", index: number, value: string) =>
    change((current) => ({ [key]: current[key].map((item, at) => (at === index ? value : item)) }));
  const removeListItem = (key: "unknown_facts" | "criteria", index: number) =>
    change((current) => ({ [key]: current[key].filter((_, at) => at !== index) }));

  const defaults = useDefaults();
  const persona = personas.data?.find((item) => item.id === input.persona_id);
  const opening = persona ? defaults.data?.first_words[persona.language] : undefined;
  const agentData = sendsAgentData(agent);
  const limit = settings.data?.values.limits.max_scenario_data_sets ?? MAX_DATA_SETS;
  const problem = dataSetsProblem(input.data_sets);
  const factNames = input.data_sets[0].known_facts.map((fact) => fact.name);
  const unknownIn = (text: string) => unknownPlaceholders(text, factNames);
  const badPlaceholders = [input.instructions, ...input.criteria].some(
    (text) => unknownIn(text).length > 0,
  );

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const valid =
      Boolean(input.name) &&
      Boolean(input.persona_id) &&
      Boolean(input.instructions) &&
      input.criteria.length > 0 &&
      problem === null &&
      !badPlaceholders;
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
      <DialogContent
        className={cn(
          "flex max-h-[90vh] flex-col gap-0 p-0",
          draft.data_sets.length > 1 ? "sm:max-w-4xl" : "sm:max-w-2xl",
        )}
      >
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle>{id ? "Edit scenario" : "New scenario"}</DialogTitle>
          {scenario?.forked_from_id && (
            <DialogDescription>
              <ForkedFrom kind="scenario" id={scenario.forked_from_id} />
            </DialogDescription>
          )}
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
                Write a fact's name in double braces, such as <code>{"{{Moving to}}"}</code>, and
                each call uses the value of its data set.
              </FieldDescription>
              {submitted && !input.instructions && (
                <FieldError>Tell the caller what to do on this call.</FieldError>
              )}
              <TextChecks
                unknown={unknownIn(input.instructions)}
                factNames={factNames}
                fixed={fixedValues(input.instructions, input.data_sets)}
                onReplace={(value, fact) =>
                  change((current) => ({
                    instructions: withPlaceholder(current.instructions, value, fact),
                  }))
                }
              />
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

            <DataSetsGrid
              dataSets={draft.data_sets}
              agentData={agentData}
              limit={limit}
              submitted={submitted}
              problem={problem}
              onChange={(dataSets) => change(() => ({ data_sets: dataSets }))}
            />

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
                The caller never sees these. Write what the agent must say or do on the call. Write
                a fact's name in double braces for a value that changes between data sets.
              </FieldDescription>
              <div className="grid gap-2">
                {draft.criteria.map((text, index) => (
                  <div key={index} className="grid gap-1.5">
                    <div className="flex gap-2">
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
                    <TextChecks
                      unknown={unknownIn(text)}
                      factNames={factNames}
                      fixed={fixedValues(text, input.data_sets)}
                      onReplace={(value, fact) =>
                        change((current) => ({
                          criteria: current.criteria.map((item, at) =>
                            at === index ? withPlaceholder(item, value, fact) : item,
                          ),
                        }))
                      }
                    />
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

            <CallerModelField
              value={draft.caller}
              onChange={(caller) => change(() => ({ caller }))}
            />
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

/** Under a text that takes placeholders: a placeholder that names no known fact keeps the
 * scenario from saving; a value written for one data set only is a warning, with a fix. */
function TextChecks({
  unknown,
  factNames,
  fixed,
  onReplace,
}: {
  unknown: string[];
  factNames: string[];
  fixed: { value: string; dataSet: string; fact: string }[];
  onReplace: (value: string, fact: string) => void;
}) {
  return (
    <>
      {unknown.map((name) => (
        <FieldError key={name}>
          There is no fact named “{name}”.{" "}
          {factNames.length > 0
            ? `Use one of: ${factNames.join(", ")}.`
            : "Add a known fact first."}
        </FieldError>
      ))}
      {fixed.map(({ value, dataSet, fact }) => (
        <p key={`${value}-${fact}`} className="text-s-400 text-status-warning-text">
          “{value}” is a value of the data set {dataSet}; the other data sets have other values
          here. Use <code>{`{{${fact}}}`}</code>.{" "}
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto px-0"
            onClick={() => onReplace(value, fact)}
          >
            Replace it
          </Button>
        </p>
      ))}
    </>
  );
}

/** The caller's model for this scenario. Most scenarios keep the default, so it stays one line
 * until changed. */
function CallerModelField({
  value,
  onChange,
}: {
  value: CallerModel | null;
  onChange: (caller: CallerModel | null) => void;
}) {
  const settings = useSettings();
  const fallback = settings.data?.values.caller;
  const [open, setOpen] = useState(value !== null);
  const model = value?.model ?? fallback?.model;
  if (!open || model === undefined) {
    const shown = value ?? fallback;
    return (
      <div className="flex items-center gap-3 border-t pt-4">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="text-s-500">Caller model</span>
          <span className="text-s-400 text-muted-foreground">
            {!value && "Default"}
            {shown &&
              `${value ? "" : ": "}${shown.model}, ${shown.reasoning_effort ?? "default"} reasoning effort`}
            {!shown && settings.isError && " (the settings did not load)"}
          </span>
        </div>
        <Button
          type="button"
          variant="link"
          size="sm"
          disabled={model === undefined}
          onClick={() => setOpen(true)}
        >
          Change
        </Button>
      </div>
    );
  }
  return (
    <FieldSet className="border-t pt-4">
      <div className="flex items-baseline justify-between">
        <FieldLegend variant="label">Caller model</FieldLegend>
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={() => {
            onChange(null);
            setOpen(false);
          }}
        >
          Use the default
        </Button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="scenario-caller-model">Model</FieldLabel>
          <ModelCombobox
            id="scenario-caller-model"
            value={value?.model ?? null}
            inherit={fallback?.model}
            inheritName="Default"
            onValueChange={(next) => {
              if (next !== (value?.model ?? null)) {
                onChange(next === null ? null : { model: next, reasoning_effort: null });
              }
            }}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="scenario-caller-effort">Reasoning effort</FieldLabel>
          <EffortSelect
            id="scenario-caller-effort"
            model={model}
            value={value ? value.reasoning_effort : (fallback?.reasoning_effort ?? null)}
            onValueChange={(effort) => onChange({ model, reasoning_effort: effort })}
            unset="default"
          />
        </Field>
      </div>
      <FieldDescription>
        A stronger model follows long instructions better, but answers slower. A long pause can make
        the agent ask if the caller is still there.
      </FieldDescription>
    </FieldSet>
  );
}
