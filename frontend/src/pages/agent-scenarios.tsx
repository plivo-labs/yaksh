import { ChevronRight, ListChecks, Plus } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useScenarios } from "@/lib/queries";
import type { Agent, Scenario } from "@/lib/types";
import { ScenarioDialog } from "@/pages/scenario-dialog";

function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function AgentScenarios({ agent }: { agent: Agent }) {
  const scenarios = useScenarios(agent.id);
  const [editing, setEditing] = useState<Scenario | "new" | null>(null);
  const scenario = editing === "new" ? undefined : (editing ?? undefined);

  return (
    <section className="grid max-w-2xl gap-4">
      <div className="flex items-end justify-between gap-4">
        <div className="grid gap-1">
          <h2 className="font-heading text-xl font-semibold tracking-tight">Scenarios</h2>
          <p className="text-sm text-muted-foreground">
            What the caller wants, and what the agent must do on the call.
          </p>
        </div>
        {scenarios.data && scenarios.data.length > 0 && (
          <Button variant="outline" onClick={() => setEditing("new")}>
            <Plus />
            New scenario
          </Button>
        )}
      </div>
      {scenarios.isPending ? (
        <Skeleton className="h-32" />
      ) : scenarios.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load scenarios</AlertTitle>
          <AlertDescription>{scenarios.error.message}</AlertDescription>
        </Alert>
      ) : scenarios.data.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ListChecks />
            </EmptyMedia>
            <EmptyTitle>No scenarios</EmptyTitle>
            <EmptyDescription>Every call follows a scenario. Create one to start.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setEditing("new")}>
              <Plus />
              New scenario
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <ul className="divide-y overflow-hidden rounded-xl border">
          {scenarios.data.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => setEditing(item)}
                className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors duration-150 outline-none hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset active:bg-muted"
              >
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate text-sm font-medium">{item.name}</span>
                  <span className="truncate text-sm text-muted-foreground">{item.goal}</span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {counted(item.known_facts.length, "fact", "facts")},{" "}
                  {counted(item.criteria.length, "criterion", "criteria")}
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </button>
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
    </section>
  );
}
