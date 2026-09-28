import { ListChecks, Plus } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyContent, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useScenarios } from "@/lib/queries";
import type { Scenario } from "@/lib/types";
import { ScenarioDialog } from "@/pages/scenario-dialog";

function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function AgentScenarios({ agentId }: { agentId: string }) {
  const scenarios = useScenarios(agentId);
  const [editing, setEditing] = useState<Scenario | "new" | null>(null);
  const scenario = editing === "new" ? undefined : (editing ?? undefined);

  return (
    <section className="grid max-w-5xl gap-4">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-heading text-xl font-semibold tracking-tight">Scenarios</h2>
        <Button variant="outline" onClick={() => setEditing("new")}>
          <Plus />
          New scenario
        </Button>
      </div>
      {scenarios.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : scenarios.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load scenarios</AlertTitle>
          <AlertDescription>{scenarios.error.message}</AlertDescription>
        </Alert>
      ) : scenarios.data.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ListChecks />
            </EmptyMedia>
            <EmptyTitle>No scenarios</EmptyTitle>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" onClick={() => setEditing("new")}>
              Create a scenario
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {scenarios.data.map((item) => (
            <li key={item.id}>
              <Card className="relative h-full transition-colors has-[[data-slot=card-link]:focus-visible]:ring-2 has-[[data-slot=card-link]:focus-visible]:ring-ring/50 hover:bg-muted/40">
                <CardHeader>
                  <CardTitle>
                    <button
                      type="button"
                      data-slot="card-link"
                      onClick={() => setEditing(item)}
                      className="text-left outline-none after:absolute after:inset-0 after:rounded-[inherit]"
                    >
                      {item.name}
                    </button>
                  </CardTitle>
                  <CardDescription className="line-clamp-2">{item.goal}</CardDescription>
                  <CardDescription>
                    {counted(item.known_facts.length, "fact", "facts")} ·{" "}
                    {counted(item.criteria.length, "criterion", "criteria")}
                  </CardDescription>
                </CardHeader>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {editing !== null && (
        <ScenarioDialog
          key={scenario?.id ?? "new"}
          agentId={agentId}
          scenario={scenario}
          onClosed={() => setEditing(null)}
        />
      )}
    </section>
  );
}
