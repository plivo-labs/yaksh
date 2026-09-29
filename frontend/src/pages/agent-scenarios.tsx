import { PhoneIncoming, PhoneOutgoing, Plus } from "lucide-react";
import { useState } from "react";

import { Panel, PanelHeader } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAgents, useScenarios } from "@/lib/queries";
import type { Agent, Scenario } from "@/lib/types";
import { ScenarioDialog } from "@/pages/scenario-dialog";
import { StartCallDialog } from "@/pages/start-call-dialog";

function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function AgentScenarios({ agent }: { agent: Agent }) {
  const scenarios = useScenarios(agent.id);
  const agents = useAgents();
  const outbound = agent.direction === "outbound";
  const [editing, setEditing] = useState<Scenario | "new" | null>(null);
  const scenario = editing === "new" ? undefined : (editing ?? undefined);

  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title="Scenarios"
        action={
          scenarios.data &&
          scenarios.data.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => setEditing("new")}>
              <Plus />
              New scenario
            </Button>
          )
        }
      />
      {scenarios.isPending ? (
        <div className="grid gap-3 p-5">
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
        </div>
      ) : scenarios.isError ? (
        <p className="px-5 py-4 text-sm text-destructive">{scenarios.error.message}</p>
      ) : scenarios.data.length === 0 ? (
        <div className="grid justify-items-start gap-3 px-5 py-6">
          <p className="text-sm text-muted-foreground">No scenarios yet.</p>
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus />
            New scenario
          </Button>
        </div>
      ) : (
        <ul className="divide-y">
          {scenarios.data.map((item) => (
            <li key={item.id} className="flex items-center gap-2 pr-4">
              <button
                type="button"
                onClick={() => setEditing(item)}
                className="flex min-w-0 flex-1 items-center gap-4 py-3 pl-5 text-left outline-none transition-colors duration-150 hover:bg-foreground/[0.025] focus-visible:bg-foreground/[0.04] focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
              >
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate text-sm font-medium">{item.name}</span>
                  <span className="truncate text-sm text-muted-foreground">{item.goal}</span>
                </span>
                <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
                  {counted(item.known_facts.length, "fact", "facts")},{" "}
                  {counted(item.criteria.length, "criterion", "criteria")}
                </span>
              </button>
              <StartCallDialog
                agents={agents.data ?? [agent]}
                agentId={agent.id}
                scenarioId={item.id}
                render={
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={`${outbound ? "Trigger" : "Ring"} ${item.name}`}
                  />
                }
              >
                {outbound ? <PhoneIncoming /> : <PhoneOutgoing />}
                {outbound ? "Trigger" : "Ring"}
              </StartCallDialog>
            </li>
          ))}
        </ul>
      )}

      {editing !== null && (
        <ScenarioDialog
          key={scenario?.id ?? "new"}
          agent={agent}
          scenario={scenario}
          onClosed={() => setEditing(null)}
        />
      )}
    </Panel>
  );
}
