import { useState } from "react";
import { toast } from "sonner";

import { DraftDialog } from "@/components/draft-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { FieldDescription, FieldError, FieldLegend, FieldSet } from "@/components/ui/field";
import { forkWords } from "@/lib/drafts";
import { forkSaver } from "@/lib/names";
import { scenarioNames, useDeleteScenario, useForkScenario, useSaveScenario } from "@/lib/queries";
import type { Agent, DataSet, Fact, Scenario, ScenarioInput } from "@/lib/types";

function changed(label: string, from: string, to: string) {
  return (
    <>
      {label} <span className="line-through">{from}</span> → {to}
    </>
  );
}

function factChanges(label: string, before: Fact[], after: Fact[]) {
  return after.flatMap((fact, index) => {
    const was = before[index];
    return was && was.value !== fact.value
      ? [changed(`${label} ${fact.name}:`, was.value, fact.value)]
      : [];
  });
}

function listChanges(label: string, before: string[], after: string[]) {
  return [
    ...after.filter((item) => !before.includes(item)).map((item) => <>{`${label}: ${item}`}</>),
    ...before
      .filter((item) => !after.includes(item))
      .map((item) => (
        <>
          {label} removed: <span className="line-through">{item}</span>
        </>
      )),
  ];
}

function textChange(label: string, text: string) {
  return (
    <details>
      <summary className="cursor-pointer">{label} changed</summary>
      <p className="mt-1 whitespace-pre-line text-foreground">{text}</p>
    </details>
  );
}

/** The data set's distinguishing values, for the checklist: its first two known facts. */
function summary(dataSet: DataSet): string {
  return dataSet.known_facts
    .slice(0, 2)
    .map((fact) => fact.value)
    .join(" · ");
}

/** Fork of a scenario: Generate writes forks from an instruction for review; the manual path
 * saves an exact copy at once and opens it for editing. Both keep the data sets checked. */
export function ScenarioFork({
  agent,
  scenario,
  onOpen,
  onClosed,
}: {
  agent: Agent;
  scenario: Scenario;
  /** Shows a scenario: a saved fork, with its editor open when it was forked manually. */
  onOpen: (id: string, editing?: Scenario) => void;
  onClosed: () => void;
}) {
  const fork = useForkScenario(agent.id);
  const create = useSaveScenario(agent.id);
  const remove = useDeleteScenario(agent.id);
  const many = scenario.data_sets.length > 1;
  const [unchecked, setUnchecked] = useState<ReadonlySet<string>>(new Set());
  const kept = scenario.data_sets.filter((dataSet) => !unchecked.has(dataSet.id ?? ""));
  const keptIds = many ? kept.map((dataSet) => dataSet.id ?? "") : undefined;

  const forkManually = () =>
    fork.mutate(
      { id: scenario.id, data_set_ids: keptIds },
      {
        onSuccess: (copy) => {
          onOpen(copy.id, copy);
          toast.success("Fork created", {
            description: `"${copy.name}" is a copy. Change what you need and save.`,
            action: {
              label: "Undo",
              onClick: () => void remove.mutateAsync(copy.id).then(() => onOpen(scenario.id)),
            },
          });
          onClosed();
        },
        onError: (error) =>
          toast.error("Could not fork the scenario", { description: error.message }),
      },
    );

  const changes = (draft: ScenarioInput) => [
    ...draft.data_sets.flatMap((dataSet) => {
      const was = scenario.data_sets.find((item) => item.name === dataSet.name);
      if (!was) return [];
      const prefix = many ? `${dataSet.name}, ` : "";
      return [
        ...factChanges(`${prefix}fact`, was.known_facts, dataSet.known_facts),
        ...factChanges(`${prefix}agent data`, was.agent_data, dataSet.agent_data),
      ];
    }),
    ...listChanges("Not known", scenario.unknown_facts, draft.unknown_facts),
    ...listChanges("Criterion", scenario.criteria, draft.criteria),
    ...(draft.instructions === scenario.instructions
      ? []
      : [textChange("Instructions", draft.instructions)]),
    ...(many ? [<>Data sets: {draft.data_sets.map((dataSet) => dataSet.name).join(", ")}</>] : []),
  ];

  const check = (id: string, on: boolean) =>
    setUnchecked((current) => {
      const next = new Set(current);
      if (on) next.delete(id);
      else next.add(id);
      return next;
    });

  const checklist = many && (
    <div className="border-t pt-4">
      <FieldSet>
        <FieldLegend variant="label">Data sets in the fork</FieldLegend>
        <FieldDescription>
          Each fork gets the checked data sets. A generated fork changes their values when the
          change needs it.
        </FieldDescription>
        <label className="flex items-center gap-3 text-s-400">
          <Checkbox
            checked={unchecked.size === 0}
            indeterminate={unchecked.size > 0 && kept.length > 0}
            onCheckedChange={(on) =>
              setUnchecked(
                on ? new Set() : new Set(scenario.data_sets.map((item) => item.id ?? "")),
              )
            }
          />
          Select all
          <span className="ml-auto text-muted-foreground">
            {kept.length} of {scenario.data_sets.length}
          </span>
        </label>
        <ul className="divide-y rounded-md border">
          {scenario.data_sets.map((dataSet) => (
            <li key={dataSet.id}>
              <label className="flex items-start gap-3 px-3 py-2.5">
                <Checkbox
                  className="mt-0.5"
                  checked={!unchecked.has(dataSet.id ?? "")}
                  onCheckedChange={(on) => check(dataSet.id ?? "", on)}
                />
                <span className="grid min-w-0 gap-0.5">
                  <span className="text-s-500">{dataSet.name}</span>
                  <span className="truncate text-xs-400 text-muted-foreground">
                    {summary(dataSet)}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
        {kept.length === 0 && <FieldError>Check at least one data set.</FieldError>}
      </FieldSet>
    </div>
  );

  return (
    <DraftDialog<ScenarioInput>
      words={forkWords("scenario")}
      originalName={scenario.name}
      path={`/scenarios/${scenario.id}/forks/draft`}
      body={keptIds ? { data_set_ids: keptIds } : undefined}
      inputExtra={checklist}
      ready={kept.length > 0}
      changes={changes}
      manual={{
        label:
          many && kept.length < scenario.data_sets.length
            ? `Skip, fork manually with ${kept.length} ${kept.length === 1 ? "data set" : "data sets"}`
            : "Skip, fork manually",
        onClick: () => kept.length > 0 && forkManually(),
      }}
      save={forkSaver(
        () => scenarioNames(agent.id),
        (draft) => create.mutateAsync(draft),
      )}
      onSaved={(ids) => {
        toast.success(`Saved ${ids.length === 1 ? "1 fork" : `${ids.length} forks`}`);
        if (ids[0]) onOpen(ids[0]);
      }}
      onClosed={onClosed}
    />
  );
}
