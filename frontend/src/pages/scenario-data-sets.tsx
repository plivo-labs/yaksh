import { Plus } from "lucide-react";
import { Fragment, type ReactNode, type SubmitEvent, useState } from "react";
import { toast } from "sonner";

import { DraftDialog } from "@/components/draft-dialog";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { collapsed, nextDataSetName, normalized, type Piece, pieces } from "@/lib/data-sets";
import { counted } from "@/lib/format";
import { freeName } from "@/lib/names";
import { useSaveDataSets, useSettings } from "@/lib/queries";
import {
  type Agent,
  type DataSet,
  type Fact,
  MAX_DATA_SETS,
  MAX_FORKS,
  type Scenario,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_DATA_SET_NAME_CHARS = 40;

/** The text with each `{{fact}}` shown as the value it takes in the data set. */
export function Filled({ text, facts }: { text: string; facts: Fact[] }) {
  return (
    <>
      {pieces(text, facts).map((piece: Piece, index) =>
        "text" in piece ? (
          <Fragment key={index}>{piece.text}</Fragment>
        ) : (
          <span
            key={index}
            title={piece.fact}
            className={cn(
              "rounded-sm px-1 py-px",
              piece.value === null
                ? "bg-destructive/10 text-destructive"
                : "bg-brand-text/10 text-brand-text",
            )}
          >
            {piece.value ?? `{{${piece.fact}}}`}
          </span>
        ),
      )}
    </>
  );
}

/** The id the server gave the data set with this name. */
function idOf(scenario: Scenario, name: string): string {
  return (
    scenario.data_sets.find((dataSet) => normalized(dataSet.name) === normalized(name))?.id ?? ""
  );
}

/** Saves the scenario's data sets, then offers Undo. Undo puts back the data sets the change
 * replaced, and only while the scenario is still at the version the change saved, so it never
 * overwrites a later change. */
function useDataSetChange(agent: Agent, scenario: Scenario) {
  const save = useSaveDataSets(agent.id, scenario.id);
  return {
    pending: save.isPending,
    change: (next: DataSet[], title: string, description: string) =>
      save.mutateAsync(next).then((saved) => {
        toast.success(title, {
          description: `${description} Saved as version ${saved.current_version}.`,
          action: {
            label: "Undo",
            onClick: () =>
              void api<Scenario>(`/scenarios/${scenario.id}`)
                .then((current) => {
                  if (current.current_version !== saved.current_version)
                    throw new Error(
                      `the scenario changed since, to version ${current.current_version}`,
                    );
                  return save.mutateAsync(scenario.data_sets);
                })
                .catch((error: Error) =>
                  toast.error("Could not undo", { description: error.message }),
                ),
          },
        });
        return saved;
      }),
  };
}

/** The root of the data set tabs when the scenario has more than one data set. */
export function DataSetTabs({
  scenario,
  selected,
  onSelect,
  children,
}: {
  scenario: Scenario;
  selected: DataSet;
  onSelect: (id: string) => void;
  children: ReactNode;
}) {
  if (scenario.data_sets.length < 2) return <>{children}</>;
  return (
    <Tabs value={selected.id} onValueChange={(id) => onSelect(String(id))}>
      {children}
    </Tabs>
  );
}

/** The scenario as the chosen data set plays it: the panel of its tab. */
export function DataSetPanel({
  scenario,
  selected,
  children,
}: {
  scenario: Scenario;
  selected: DataSet;
  children: ReactNode;
}) {
  if (scenario.data_sets.length < 2) return <>{children}</>;
  return <TabsContent value={selected.id}>{children}</TabsContent>;
}

/** The tabs of the scenario's data sets, and adding, editing and removing them. The page
 * shows the scenario with the values of the chosen tab; with more than one data set, it holds
 * this bar and the tab's panel in one Tabs root. */
export function DataSetBar({
  agent,
  scenario,
  selected,
  onSelect,
}: {
  agent: Agent;
  scenario: Scenario;
  selected: DataSet;
  /** Shows the data set with this id. */
  onSelect: (id: string) => void;
}) {
  const settings = useSettings();
  const limit = settings.data?.values.limits.max_scenario_data_sets ?? MAX_DATA_SETS;
  const room = limit - scenario.data_sets.length;
  const [dialog, setDialog] = useState<"copy" | "edit" | "write" | null>(null);
  const many = scenario.data_sets.length > 1;

  return (
    <div className="grid gap-2 px-6 pt-4">
      <div className="flex flex-wrap items-end justify-between gap-x-4 border-b">
        <div className="flex min-w-0 items-end">
          {many ? (
            <TabsList variant="line" aria-label="Data sets" className="max-w-full overflow-x-auto">
              {scenario.data_sets.map((dataSet) => (
                <TabsTrigger key={dataSet.id} value={dataSet.id}>
                  {dataSet.name}
                </TabsTrigger>
              ))}
            </TabsList>
          ) : (
            <span className="py-2 text-s-500">Values</span>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size={many ? "icon-sm" : "sm"}
                  className="mb-1 ml-1"
                  aria-label="Add data set"
                  disabled={room <= 0}
                  title={room <= 0 ? `A scenario holds at most ${limit} data sets.` : undefined}
                />
              }
            >
              <Plus />
              {!many && "Add data set"}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-72">
              <DropdownMenuItem onClick={() => setDialog("copy")}>
                <span className="grid gap-0.5">
                  <span>Copy {selected.name}</span>
                  <span className="text-xs-400 text-muted-foreground">
                    Start from its values and change what differs.
                  </span>
                </span>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setDialog("write")}>
                <span className="grid gap-0.5">
                  <span>Write with AI</span>
                  <span className="text-xs-400 text-muted-foreground">
                    Say what should change. AI writes up to {Math.min(MAX_FORKS, room)}{" "}
                    {Math.min(MAX_FORKS, room) === 1 ? "data set" : "data sets"}.
                  </span>
                </span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <Button variant="link" size="sm" className="mb-1 px-0" onClick={() => setDialog("edit")}>
          {many ? `Edit ${selected.name}` : "Edit values"}
        </Button>
      </div>
      <p className="text-xs-400 text-muted-foreground">
        {many
          ? `A run plays each of the ${scenario.data_sets.length} data sets. The text below shows the values of ${selected.name}.`
          : "One data set. Add another to play this scenario again with other names, places or dates."}
      </p>

      {(dialog === "copy" || dialog === "edit") && (
        <DataSetDialog
          agent={agent}
          scenario={scenario}
          editing={dialog === "edit" ? selected : null}
          from={selected}
          onSaved={onSelect}
          onClosed={() => setDialog(null)}
        />
      )}
      {dialog === "write" && (
        <WriteDataSets
          agent={agent}
          scenario={scenario}
          room={room}
          onSaved={onSelect}
          onClosed={() => setDialog(null)}
        />
      )}
    </div>
  );
}

/** One data set: a new one that starts as a copy of `from`, or `editing`. The names are the
 * scenario's, the same in every data set; only the values change here. */
function DataSetDialog({
  agent,
  scenario,
  editing,
  from,
  onSaved,
  onClosed,
}: {
  agent: Agent;
  scenario: Scenario;
  editing: DataSet | null;
  from: DataSet;
  /** Shows the data set with this id. */
  onSaved: (id: string) => void;
  onClosed: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [draft, setDraft] = useState<DataSet>(
    () =>
      editing ?? {
        name: nextDataSetName(scenario.data_sets),
        known_facts: from.known_facts,
        agent_data: from.agent_data,
      },
  );
  const [submitted, setSubmitted] = useState(false);
  const { change, pending } = useDataSetChange(agent, scenario);
  const [error, setError] = useState<string | null>(null);
  const outbound = agent.direction === "outbound";
  const others = scenario.data_sets.filter((dataSet) => dataSet.id !== editing?.id);
  const name = draft.name.trim();
  const nameProblem = !name
    ? "Enter a name."
    : others.some((dataSet) => normalized(dataSet.name) === normalized(name))
      ? `There is already a data set named ${name}.`
      : null;
  const empty = [...draft.known_facts, ...(outbound ? draft.agent_data : [])].some(
    (fact) => !fact.value.trim(),
  );
  const trimmed: DataSet = {
    ...draft,
    name,
    known_facts: draft.known_facts.map((fact) => ({ ...fact, value: fact.value.trim() })),
    agent_data: draft.agent_data.map((fact) => ({ ...fact, value: fact.value.trim() })),
  };

  const setValue = (kind: "known_facts" | "agent_data", index: number, value: string) =>
    setDraft((current) => ({
      ...current,
      [kind]: current[kind].map((fact, at) => (at === index ? { ...fact, value } : fact)),
    }));

  const finish = (
    next: DataSet[],
    title: string,
    description: string,
    show: (saved: Scenario) => string,
  ) =>
    change(next, title, description)
      .then((saved) => {
        onSaved(show(saved));
        setOpen(false);
      })
      .catch((failure: Error) => setError(failure.message));

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (nameProblem || empty) return;
    if (editing)
      void finish(
        scenario.data_sets.map((dataSet) => (dataSet.id === editing.id ? trimmed : dataSet)),
        `${name} saved`,
        "",
        () => editing.id ?? "",
      );
    else
      void finish(
        [...scenario.data_sets, trimmed],
        `${name} added`,
        `A run now plays ${scenario.data_sets.length + 1} data sets.`,
        (saved) => idOf(saved, name),
      );
  };

  const removeIt = () => {
    if (!editing) return;
    const rest = scenario.data_sets.filter((dataSet) => dataSet.id !== editing.id);
    void finish(
      rest,
      `${editing.name} removed`,
      `A run now plays ${counted(rest.length, "data set", "data sets")}.`,
      () => rest[0].id ?? "",
    );
  };

  const values = (kind: "known_facts" | "agent_data", mono: boolean) => (
    <div className="grid items-center gap-x-3 gap-y-2 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
      {draft[kind].map((fact, index) => (
        <Fragment key={index}>
          <label
            htmlFor={`data-set-${kind}-${index}`}
            className={cn("text-s-400 text-muted-foreground wrap-anywhere", mono && "font-mono")}
          >
            {fact.name}
          </label>
          <Input
            id={`data-set-${kind}-${index}`}
            maxLength={500}
            aria-invalid={submitted && !fact.value.trim()}
            value={fact.value}
            onChange={(e) => setValue(kind, index, e.target.value)}
          />
        </Fragment>
      ))}
    </div>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !pending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-xl">
        <DialogHeader className="border-b px-6 pt-6 pb-4">
          <DialogTitle>{editing ? `Edit ${editing.name}` : "New data set"}</DialogTitle>
          <DialogDescription>
            {editing ? scenario.name : `A copy of ${from.name}. Change the values that differ.`}
          </DialogDescription>
        </DialogHeader>
        <form
          id="data-set-form"
          noValidate
          onSubmit={submit}
          className="min-h-0 flex-1 overflow-y-auto px-6 py-5"
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="data-set-name">Name</FieldLabel>
              <Input
                id="data-set-name"
                maxLength={MAX_DATA_SET_NAME_CHARS}
                aria-invalid={submitted && nameProblem !== null}
                value={draft.name}
                onChange={(e) => setDraft((current) => ({ ...current, name: e.target.value }))}
              />
              <FieldDescription>
                Short and different from the other data sets. Runs show it next to the scenario
                name.
              </FieldDescription>
              {submitted && nameProblem && <FieldError>{nameProblem}</FieldError>}
            </Field>
            <FieldSet>
              <FieldLegend variant="label">What the caller knows</FieldLegend>
              <FieldDescription>
                Write dates relative to today, for example next Thursday.
              </FieldDescription>
              {draft.known_facts.length > 0 ? (
                values("known_facts", false)
              ) : (
                <span className="text-s-400 text-muted-foreground">
                  The scenario has no facts yet. Add them with Edit on the scenario.
                </span>
              )}
            </FieldSet>
            {outbound && draft.agent_data.length > 0 && (
              <FieldSet>
                <FieldLegend variant="label">Data sent to the agent</FieldLegend>
                <FieldDescription>The caller does not see these.</FieldDescription>
                {values("agent_data", true)}
              </FieldSet>
            )}
            <p className="text-s-400 text-muted-foreground">
              The names are the same in every data set. To add, rename or remove a name, use Edit on
              the scenario.
            </p>
            {submitted && empty && <FieldError>Every name needs a value.</FieldError>}
          </FieldGroup>
        </form>
        {error && <FieldError className="px-6 pb-3">{error}</FieldError>}
        <DialogFooter className="border-t px-6 py-4 sm:justify-between">
          {editing && scenario.data_sets.length > 1 ? (
            <Button
              type="button"
              variant="ghost"
              className="text-destructive"
              disabled={pending}
              onClick={removeIt}
            >
              Remove data set
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button type="button" variant="ghost" disabled={pending} onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" form="data-set-form" disabled={pending}>
              {pending && <Spinner />}
              {editing ? "Save" : "Add data set"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Data sets that AI writes from an instruction, reviewed and added together. */
function WriteDataSets({
  agent,
  scenario,
  room,
  onSaved,
  onClosed,
}: {
  agent: Agent;
  scenario: Scenario;
  room: number;
  /** Shows the data set with this id. */
  onSaved: (id: string) => void;
  onClosed: () => void;
}) {
  const { change } = useDataSetChange(agent, scenario);
  const outbound = agent.direction === "outbound";
  const first = scenario.data_sets[0];
  const line = (facts: Fact[]) => facts.map((fact) => `${fact.name} ${fact.value}`).join(" · ");

  return (
    <DraftDialog<DataSet>
      words={{
        title: "Write data sets",
        one: "data set",
        many: "data sets",
        event: "data_set",
        placeholder:
          "Name a change for each data set. For example: moves to Tokyo, Dubai and Sydney, each with a different caller.",
        verb: "Add",
      }}
      originalName={scenario.name}
      path={`/scenarios/${scenario.id}/data-sets/draft`}
      most={Math.min(MAX_FORKS, room)}
      inputExtra={
        <div className="grid gap-1.5 rounded-md border bg-muted/40 px-4 py-3">
          <span className="text-xs-500 text-muted-foreground">Each data set fills these names</span>
          <span className="text-s-400">
            {first.known_facts.map((fact) => fact.name).join(", ") || "No facts yet"}
          </span>
          {outbound && first.agent_data.length > 0 && (
            <span className="font-mono text-s-400 text-muted-foreground">
              {first.agent_data.map((fact) => fact.name).join(", ")}
            </span>
          )}
          <span className="text-xs-400 text-muted-foreground">
            {outbound && first.agent_data.length > 0
              ? "The instructions and the criteria stay the same. The values agree: the city the caller names is the city in the agent data."
              : "The instructions and the criteria stay the same."}
          </span>
        </div>
      }
      changes={(draft) => [
        line(draft.known_facts),
        ...(outbound && draft.agent_data.length > 0
          ? [`Agent data: ${line(draft.agent_data)}`]
          : []),
      ]}
      save={async (chosen, done) => {
        const taken = new Set(scenario.data_sets.map((dataSet) => normalized(dataSet.name)));
        const added = chosen.map(({ draft }) => {
          const name = freeName(collapsed(draft.name), taken, MAX_DATA_SET_NAME_CHARS, normalized);
          taken.add(normalized(name));
          return { name, known_facts: draft.known_facts, agent_data: draft.agent_data };
        });
        const names = added.map((dataSet) => dataSet.name);
        const saved = await change(
          [...scenario.data_sets, ...added],
          `${counted(added.length, "data set", "data sets")} added`,
          `${names.join(", ")}. A run now plays ${scenario.data_sets.length + added.length} data sets.`,
        );
        chosen.forEach(({ index }, at) => done(index, idOf(saved, names[at])));
        onSaved(idOf(saved, names[0]));
      }}
      onClosed={onClosed}
    />
  );
}
