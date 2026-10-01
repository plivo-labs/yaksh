import { ChevronDown, PhoneIncoming, PhoneOutgoing, Play, Plus, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { DeleteConfirm } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
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
import { when } from "@/lib/format";
import {
  useAgents,
  useAssignPersona,
  useDeleteScenarios,
  useGenerations,
  usePersonas,
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
import { GenerateDialog } from "@/pages/generate-dialog";
import { RunDialog } from "@/pages/run-dialog";
import { ScenarioDialog } from "@/pages/scenario-dialog";
import { StartCallDialog } from "@/pages/start-call-dialog";

const ALL = "all";

function counted(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

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
      <p className={`min-w-0 flex-1 ${progress.status === "failed" ? "text-destructive" : ""}`}>
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
  const personas = usePersonas();
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
  const personaNames = new Map((personas.data ?? []).map((persona) => [persona.id, persona.name]));
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
    <Panel className="overflow-hidden">
      <PanelHeader
        title="Scenarios"
        action={
          items.length > 0 && (
            <div className="flex gap-2">
              {generateButton("outline")}
              {newButton}
            </div>
          )
        }
      />
      {generation.progress && (
        <GenerationNotice
          progress={generation.progress}
          onStop={generation.stop}
          onDismiss={generation.dismiss}
        />
      )}
      {scenarios.isPending ? (
        <div className="grid gap-3 p-5">
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
        </div>
      ) : scenarios.isError ? (
        <p className="px-5 py-4 text-sm text-destructive">{scenarios.error.message}</p>
      ) : items.length === 0 ? (
        <div className="grid justify-items-start gap-3 px-5 py-6">
          <p className="text-sm text-muted-foreground">
            No scenarios yet. Generate them from what Truman knows about the agent, or write one.
          </p>
          <div className="flex gap-2">
            {generateButton("default")}
            {newButton}
          </div>
        </div>
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
              {selected.length > MAX_BULK ? (
                <p className="text-sm text-muted-foreground">Select at most {MAX_BULK} at once.</p>
              ) : selected.length > 0 ? (
                <>
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
                        <DropdownMenuItem key={persona.id} onClick={() => assignPersona(persona)}>
                          {persona.name}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <Button size="sm" onClick={() => setRunning(true)}>
                    <Play />
                    Run {selected.length}
                  </Button>
                  <DeleteConfirm
                    name={counted(selected.length, "scenario", "scenarios")}
                    label={`Delete ${selected.length} selected`}
                    description="Past and queued conversations are not changed."
                    pending={remove.isPending}
                    onDelete={(close) => deleteScenarios(selected, close)}
                  />
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
              <li key={item.id} className="flex items-center gap-2 pr-4 pl-5">
                <Checkbox
                  aria-label={`Select ${item.name}`}
                  checked={picked.has(item.id)}
                  onCheckedChange={(on) => pick(item.id, on)}
                />
                <button
                  type="button"
                  onClick={() => setEditing(item)}
                  className="flex min-w-0 flex-1 items-center gap-4 py-3 pl-3 text-left outline-none transition-colors duration-150 hover:bg-foreground/[0.025] focus-visible:bg-foreground/[0.04] focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
                >
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-medium">{item.name}</span>
                      <Badge variant="outline" className="shrink-0">
                        {CATEGORY_LABELS[item.category]}
                      </Badge>
                      {generation.newIds.has(item.id) && <Badge className="shrink-0">New</Badge>}
                    </span>
                    <span className="truncate text-sm text-muted-foreground">
                      {item.description ?? item.goal}
                    </span>
                  </span>
                  <span className="hidden shrink-0 justify-items-end gap-0.5 text-xs text-muted-foreground sm:grid">
                    <span>{personaNames.get(item.persona_id)}</span>
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
        </>
      )}

      {editing !== null && (
        <ScenarioDialog
          key={scenario?.id ?? "new"}
          agent={agent}
          scenario={scenario}
          onClosed={() => setEditing(null)}
        />
      )}
      {running && (
        <RunDialog
          agent={agent}
          choices={{ scenarios: items.filter((item) => picked.has(item.id)) }}
          onClosed={() => setRunning(false)}
        />
      )}
      {generating && (
        <GenerateDialog
          agent={agent}
          onStart={generation.start}
          onClosed={() => setGenerating(false)}
        />
      )}
    </Panel>
  );
}
