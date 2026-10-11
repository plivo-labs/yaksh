import { toast } from "sonner";

import { ForkDialog } from "@/components/fork-dialog";
import { scenarioNames, useDeleteScenario, useForkScenario, useSaveScenario } from "@/lib/queries";
import type { Agent, Fact, Scenario, ScenarioInput } from "@/lib/types";

function changed(label: string, from: string, to: string) {
  return (
    <>
      {label} <span className="line-through">{from}</span> → {to}
    </>
  );
}

function factChanges(label: string, before: Fact[], after: Fact[]) {
  const lines = after.flatMap((fact) => {
    const was = before.find((item) => item.name === fact.name);
    if (was?.value === fact.value) return [];
    return [
      was ? (
        changed(`${label} ${fact.name}:`, was.value, fact.value)
      ) : (
        <>{`${label} ${fact.name} added: ${fact.value}`}</>
      ),
    ];
  });
  for (const fact of before)
    if (!after.some((item) => item.name === fact.name))
      lines.push(<>{`${label} ${fact.name} removed`}</>);
  return lines;
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

/** Fork of a scenario: Generate writes forks from an instruction for review; the manual path
 * saves an exact copy at once and opens it for editing. */
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

  const forkManually = () =>
    fork.mutate(scenario.id, {
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
    });

  const changes = (draft: ScenarioInput) => [
    ...factChanges("Fact", scenario.known_facts, draft.known_facts),
    ...factChanges("Agent data", scenario.agent_data, draft.agent_data),
    ...listChanges("Not known", scenario.unknown_facts, draft.unknown_facts),
    ...listChanges("Criterion", scenario.criteria, draft.criteria),
    ...(draft.instructions === scenario.instructions
      ? []
      : [textChange("Instructions", draft.instructions)]),
  ];

  return (
    <ForkDialog<ScenarioInput>
      kind="scenario"
      originalName={scenario.name}
      path={`/scenarios/${scenario.id}/forks/draft`}
      changes={changes}
      onManual={forkManually}
      takenNames={() => scenarioNames(agent.id)}
      saveOne={(draft) => create.mutateAsync(draft)}
      onSaved={(ids) => {
        toast.success(`Saved ${ids.length === 1 ? "1 fork" : `${ids.length} forks`}`);
        if (ids[0]) onOpen(ids[0]);
      }}
      onClosed={onClosed}
    />
  );
}
