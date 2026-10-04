import { ChevronDown, PhoneIncoming, PhoneOutgoing, Play, Plus, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { DeleteConfirm } from "@/components/confirm-dialogs";
import { ActionPanel } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { type GenerationProgress, useGeneration } from "@/hooks/use-generation";
import { usePersonaNames } from "@/hooks/use-persona-names";
import { counted, when } from "@/lib/format";
import { APPEAR, RISE } from "@/lib/motion";
import {
  useAgents,
  useAssignPersona,
  useDeleteScenarios,
  useGenerations,
  useScenarios,
} from "@/lib/queries";
import {
  type Agent,
  CATEGORY_LABELS,
  type Generation,
  MAX_BULK,
  type Persona,
  type Scenario,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { GenerateDialog } from "@/pages/generate-dialog";
import { RunDialog } from "@/pages/run-dialog";
import { ScenarioDialog } from "@/pages/scenario-dialog";
import { StartCallDialog } from "@/pages/start-call-dialog";

const ALL = "all";

function batchLabel(generation: Generation): string {
  const kind = generation.mode === "knowledge_base" ? "Knowledge base questions" : "Generated";
  return `${kind}, ${when(generation.created_at)} (${generation.scenarios})`;
}

function progressMessage(progress: GenerationProgress): string {
  const saved = counted(progress.saved, "scenario", "scenarios");
  if (progress.status === "running") {
    return progress.planned === null
      ? "Reading the agent and planning what to test."
      : `Writing scenarios: ${progress.saved + progress.dropped.length} of ${progress.planned} done.`;
  }
  if (progress.status === "stopped") return `Stopped. ${saved} saved.`;
  if (progress.status === "failed") {
    const kept = progress.saved > 0 ? ` ${saved} saved before it stopped.` : "";
    return `The generation failed: ${progress.error}${kept}`;
  }
  const dropped =
    progress.dropped.length > 0
      ? ` ${counted(progress.dropped.length, "scenario", "scenarios")} could not be written: ${progress.dropped[0]}`
      : "";
  return `Wrote ${saved}.${dropped}`;
}

function GenerationNotice({
  progress,
  onStop,
  onDismiss,
}: {
  progress: GenerationProgress;
  onStop: () => void;
  onDismiss: () => void;
}) {
  const running = progress.status === "running";
  return (
    <div role="status" className="flex items-center gap-3 border-b bg-muted/40 px-5 py-3 text-sm">
      {running && <Spinner />}
      <p
        key={progress.status}
        className={cn("min-w-0 flex-1", progress.status === "failed" && "text-destructive", APPEAR)}
      >
        {progressMessage(progress)}
      </p>
      {running ? (
        <Button type="button" variant="outline" size="sm" onClick={onStop}>
          Stop
        </Button>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Close this message"
          onClick={onDismiss}
        >
          <X />
        </Button>
      )}
    </div>
  );
}

export function AgentScenarios({ agent }: { agent: Agent }) {
  const [batch, setBatch] = useState<string | null>(null);
  const generations = useGenerations(agent.id);
  const shownBatch = generations.data?.some((item) => item.id === batch) ? batch : null;
  const scenarios = useScenarios(agent.id, true, shownBatch);
  const agents = useAgents();
  const remove = useDeleteScenarios(agent.id);
  const assign = useAssignPersona(agent.id);
  const { personas, name: personaName } = usePersonaNames();
  const generation = useGeneration(agent.id);
  const outbound = agent.direction === "outbound";
  const [editing, setEditing] = useState<Scenario | "new" | null>(null);
  const [generating, setGenerating] = useState(false);
  const [running, setRunning] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const scenario = editing === "new" ? undefined : (editing ?? undefined);

  const items = scenarios.data ?? [];
  const selected = items.filter((item) => picked.has(item.id)).map((item) => item.id);
  const allPicked = items.length > 0 && selected.length === items.length;
  /** Changes to many scenarios at once are capped; a run is limited by the server's own cap. */
  const bulk = selected.length <= MAX_BULK;
  const pick = (id: string, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const deleteScenarios = (ids: string[], close: () => void) =>
    remove.mutate(ids, {
      onSuccess: () => {
        setPicked(new Set());
        toast.success(`Deleted ${counted(ids.length, "scenario", "scenarios")}`);
      },
      onError: (error) =>
        toast.error("Could not delete the scenarios", { description: error.message }),
      onSettled: close,
    });
  const assignPersona = (persona: Persona) =>
    assign.mutate(
      { scenario_ids: selected, persona_id: persona.id },
      {
        onSuccess: () =>
          toast.success(
            `${persona.name} is now the persona of ${counted(selected.length, "scenario", "scenarios")}`,
          ),
        onError: (error) =>
          toast.error("Could not change the persona", { description: error.message }),
      },
    );
  const batches = generations.data ?? [];
  const filterItems = [
    { value: ALL, label: "All scenarios" },
    ...batches.map((item) => ({ value: item.id, label: batchLabel(item) })),
  ];
  const generateButton = (variant: "default" | "outline") => (
    <Button
      variant={variant}
      size="sm"
      disabled={generation.running}
      onClick={() => setGenerating(true)}
    >
      <Sparkles />
      Generate
    </Button>
  );
  const newButton = (
    <Button variant="outline" size="sm" onClick={() => setEditing("new")}>
      <Plus />
      New scenario
    </Button>
  );

  return (
    <>
      <ActionPanel
        action={
          <div className="flex gap-2">
            {generateButton(scenarios.data && items.length === 0 ? "default" : "outline")}
            {newButton}
          </div>
        }
        notice={
          generation.progress && (
            <GenerationNotice
              progress={generation.progress}
              onStop={generation.stop}
              onDismiss={generation.dismiss}
            />
          )
        }
      >
        {scenarios.isPending ? (
          <div className="grid gap-3 p-5">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        ) : scenarios.isError ? (
          <p role="alert" className="px-5 py-4 text-sm text-destructive">
            {scenarios.error.message}
          </p>
        ) : items.length === 0 ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">
            No scenarios yet. Generate them from what Truman knows about the agent, or write one.
          </p>
        ) : (
          <>
            <div className="flex min-h-12 flex-wrap items-center gap-3 border-b px-5 py-2">
              <Checkbox
                aria-label="Select all scenarios"
                checked={allPicked}
                indeterminate={selected.length > 0 && !allPicked}
                onCheckedChange={(on) =>
                  setPicked(on ? new Set(items.map((item) => item.id)) : new Set())
                }
              />
              {batches.length > 0 && (
                <Select
                  items={filterItems}
                  value={shownBatch ?? ALL}
                  onValueChange={(value) => {
                    setBatch(value === ALL ? null : value);
                    setPicked(new Set());
                  }}
                >
                  <SelectTrigger aria-label="Show scenarios from" size="sm" className="min-w-0">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {filterItems.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              )}
              <div className="ml-auto flex gap-2">
                {selected.length > 0 ? (
                  <>
                    {bulk ? (
                      <DropdownMenu disabled={assign.isPending || !personas.data?.length}>
                        <DropdownMenuTrigger
                          aria-label="Set the persona of the selected scenarios"
                          render={<Button variant="outline" size="sm" />}
                        >
                          Set persona
                          <ChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {personas.data?.map((persona) => (
                            <DropdownMenuItem
                              key={persona.id}
                              onClick={() => assignPersona(persona)}
                            >
                              {persona.name}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Select at most {MAX_BULK} to change or delete them at once.
                      </p>
                    )}
                    <Button size="sm" onClick={() => setRunning(true)}>
                      <Play />
                      Run {selected.length}
                    </Button>
                    {bulk && (
                      <DeleteConfirm
                        name={counted(selected.length, "scenario", "scenarios")}
                        label={`Delete ${selected.length} selected`}
                        description="Past and queued conversations are not changed."
                        pending={remove.isPending}
                        onDelete={(close) => deleteScenarios(selected, close)}
                      />
                    )}
                  </>
                ) : (
                  shownBatch && (
                    <DeleteConfirm
                      name={`this batch of ${counted(items.length, "scenario", "scenarios")}`}
                      label="Delete this batch"
                      description="Past and queued conversations are not changed."
                      pending={remove.isPending}
                      onDelete={(close) =>
                        deleteScenarios(
                          items.map((item) => item.id),
                          close,
                        )
                      }
                    />
                  )
                )}
              </div>
            </div>
            <ul className="divide-y">
              {items.map((item) => (
                <li
                  key={item.id}
                  className={cn(
                    "flex items-center gap-3 pr-4 pl-5 transition-colors duration-150 hover:bg-muted/60 has-[[data-slot=scenario-open]:active]:bg-muted",
                    generation.newIds.has(item.id) && RISE,
                  )}
                >
                  <Checkbox
                    aria-label={`Select ${item.name}`}
                    checked={picked.has(item.id)}
                    onCheckedChange={(on) => pick(item.id, on)}
                  />
                  <button
                    type="button"
                    data-slot="scenario-open"
                    title={`${item.name}\n${item.description ?? item.goal}`}
                    onClick={() => setEditing(item)}
                    className="flex min-w-0 flex-1 items-center gap-6 py-3.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
                  >
                    <span className="grid min-w-0 flex-1 gap-1">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate text-s-500">{item.name}</span>
                        <Badge className="shrink-0">{CATEGORY_LABELS[item.category]}</Badge>
                        {generation.newIds.has(item.id) && (
                          <Badge variant="info" className="shrink-0">
                            New
                          </Badge>
                        )}
                      </span>
                      <span className="truncate text-s-400 text-muted-foreground">
                        {item.description ?? item.goal}
                      </span>
                    </span>
                    <span className="hidden shrink-0 justify-items-end gap-1 text-xs-400 text-muted-foreground sm:grid">
                      <span>{personaName(item.persona_id)}</span>
                      <span>
                        {counted(item.known_facts.length, "fact", "facts")},{" "}
                        {counted(item.criteria.length, "criterion", "criteria")}
                      </span>
                    </span>
                  </button>
                  <StartCallDialog
                    agents={agents.data ?? [agent]}
                    agentId={agent.id}
                    scenarioId={item.id}
                    render={
                      <Button
                        variant="ghost"
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
          </>
        )}
      </ActionPanel>

      {editing !== null && (
        <ScenarioDialog
          key={scenario?.id ?? "new"}
          agent={agent}
          scenario={scenario}
          onClosed={() => setEditing(null)}
        />
      )}
      {running && (
        <RunDialog agent={agent} scenarioIds={selected} onClosed={() => setRunning(false)} />
      )}
      {generating && (
        <GenerateDialog
          agent={agent}
          onStart={generation.start}
          onClosed={() => setGenerating(false)}
        />
      )}
    </>
  );
}
