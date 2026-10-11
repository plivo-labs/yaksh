import { Toggle } from "@base-ui/react/toggle";
import { ToggleGroup } from "@base-ui/react/toggle-group";
import { ChevronDown, GitFork, Pencil, Play, Plus, Sparkles, Trash2, X } from "lucide-react";
import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { DeleteConfirm, DeleteDialog } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { ForkedFrom } from "@/components/forked-from";
import { Panel } from "@/components/panel";
import { SearchInput } from "@/components/search-input";
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
import { APPEAR, REVEAL, RISE } from "@/lib/motion";
import { useAssignPersona, useDeleteScenarios, useGenerations, useScenarios } from "@/lib/queries";
import {
  type Agent,
  type Category,
  CATEGORY_ITEMS,
  CATEGORY_LABELS,
  type Fact,
  type Generation,
  MAX_BULK,
  type Persona,
  type Scenario,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { GenerateDialog } from "@/pages/generate-dialog";
import { RunDialog } from "@/pages/run-dialog";
import { ScenarioDialog } from "@/pages/scenario-dialog";
import { DataSetBar, DataSetPanel, DataSetTabs, Filled } from "@/pages/scenario-data-sets";
import { ScenarioFork } from "@/pages/scenario-fork";

const ALL = "all";

const CATEGORY_BADGE: Record<Category, "success" | "warning" | "info"> = {
  happy_path: "success",
  messy_input: "warning",
  edge_case: "info",
};

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

function matches(scenario: Scenario, text: string): boolean {
  const needle = text.toLowerCase();
  return [scenario.name, scenario.description ?? "", scenario.instructions].some((field) =>
    field.toLowerCase().includes(needle),
  );
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
    <div
      role="status"
      className="flex items-center gap-3 border-b bg-muted/40 px-5 py-3 text-p-400"
    >
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

/** The agent's scenarios as a list beside the one that is open. The list filters by category,
 * text and generation batch. A checked row stays checked while a category or text filter hides
 * it, and the actions for many scenarios take every checked row. */
export function AgentScenarios({ agent }: { agent: Agent }) {
  const [batch, setBatch] = useState<string | null>(null);
  const [category, setCategory] = useState<Category | typeof ALL>(ALL);
  const [search, setSearch] = useState("");
  const [params] = useSearchParams();
  const [openId, setOpenId] = useState<string | null>(() => params.get("scenario"));
  const generations = useGenerations(agent.id);
  const shownBatch = generations.data?.some((item) => item.id === batch) ? batch : null;
  const scenarios = useScenarios(agent.id, true, shownBatch);
  const remove = useDeleteScenarios(agent.id);
  const assign = useAssignPersona(agent.id);
  const { personas, name: personaName } = usePersonaNames();
  const generation = useGeneration(agent.id);
  const [editing, setEditing] = useState<Scenario | "new" | null>(null);
  const [forking, setForking] = useState<Scenario | null>(null);
  const [generating, setGenerating] = useState(false);
  const [running, setRunning] = useState<string[] | null>(null);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const selectAll = useRef<HTMLButtonElement>(null);
  const scenario = editing === "new" ? undefined : (editing ?? undefined);
  const finished = useRef<string | null>(null);
  const { id: generationId, progress, written, dismiss } = generation;
  // A finished generation's scenarios are checked once, so the selection bar can run them, and
  // its notice becomes a toast.
  useEffect(() => {
    if (
      progress?.status !== "done" ||
      !generationId ||
      generationId === finished.current ||
      written.length !== progress.saved
    )
      return;
    finished.current = generationId;
    setPicked(new Set(written));
    toast.success(progressMessage(progress));
    dismiss();
  }, [generationId, progress, written, dismiss]);

  const items = scenarios.data ?? [];
  const listed = items.filter(
    (item) => (category === ALL || item.category === category) && matches(item, search),
  );
  const open = listed.find((item) => item.id === openId) ?? listed[0];
  // The first row opens by default; keeping it keeps it open when new scenarios arrive above it.
  if (open && open.id !== openId) setOpenId(open.id);
  const selected = items.filter((item) => picked.has(item.id)).map((item) => item.id);
  const listedPicked = listed.filter((item) => picked.has(item.id)).length;
  const pick = (ids: string[], on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
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
  const batches = (generations.data ?? []).filter((item) => item.scenarios > 0);
  const batchItems = [
    { value: ALL, label: "All batches" },
    ...batches.map((item) => ({ value: item.id, label: batchLabel(item) })),
  ];
  const categoryItems = [
    { value: ALL, label: "All", count: items.length },
    ...CATEGORY_ITEMS.map((item) => ({
      value: item.value,
      label: item.label,
      count: items.filter((found) => found.category === item.value).length,
    })),
  ];

  return (
    <>
      <Panel className="overflow-clip">
        {generation.progress && (
          <div className={REVEAL}>
            <GenerationNotice
              progress={generation.progress}
              onStop={generation.stop}
              onDismiss={generation.dismiss}
            />
          </div>
        )}
        {scenarios.isPending ? (
          <div className="grid gap-3 p-5">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        ) : scenarios.isError ? (
          <p role="alert" className="px-5 py-4 text-p-400 text-destructive">
            {scenarios.error.message}
          </p>
        ) : items.length === 0 && !shownBatch && generation.running ? (
          <div aria-hidden className="grid gap-3 p-5">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        ) : items.length === 0 && !shownBatch ? (
          <div className="grid justify-items-center gap-4 px-5 py-10 text-center">
            <p className="text-p-400 text-muted-foreground">
              No scenarios yet. Generate them from what Yaksha knows about the agent, or write one.
            </p>
            <div className="flex gap-2">
              <Button size="sm" disabled={generation.running} onClick={() => setGenerating(true)}>
                <Sparkles />
                Generate
              </Button>
              <Button variant="outline" size="sm" onClick={() => setEditing("new")}>
                <Plus />
                Write a scenario manually
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid lg:grid-cols-[26rem_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col border-b lg:border-r lg:border-b-0">
              <div className="grid gap-2 border-b px-4 py-3">
                <div className="flex gap-2">
                  <SearchInput
                    className="min-w-0 flex-1"
                    value={search}
                    onSearch={setSearch}
                    label="Search scenarios"
                    placeholder="Search scenarios"
                  />
                  <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label="Generate scenarios"
                    title="Generate scenarios"
                    disabled={generation.running}
                    onClick={() => setGenerating(true)}
                  >
                    <Sparkles />
                  </Button>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label="Write a scenario manually"
                    title="Write a scenario manually"
                    onClick={() => setEditing("new")}
                  >
                    <Plus />
                  </Button>
                </div>
                <ToggleGroup
                  aria-label="Category"
                  value={[category]}
                  onValueChange={(value) => value[0] && setCategory(value[0])}
                  className="flex gap-0.5 rounded-md bg-muted p-0.5"
                >
                  {categoryItems.map((item) => (
                    <Toggle
                      key={item.value}
                      value={item.value}
                      className="h-[26px] grow rounded-sm px-2.5 text-xs-500 whitespace-nowrap text-muted-foreground outline-none transition-colors duration-150 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 data-pressed:bg-card data-pressed:text-foreground data-pressed:shadow-xs"
                    >
                      {item.label} <span className="tabular-nums">{item.count}</span>
                    </Toggle>
                  ))}
                </ToggleGroup>
                {batches.length > 0 && (
                  <Select
                    items={batchItems}
                    value={shownBatch ?? ALL}
                    onValueChange={(value) => {
                      setBatch(value === ALL ? null : value);
                      setPicked(new Set());
                    }}
                  >
                    <SelectTrigger aria-label="Show scenarios from" size="sm" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {batchItems.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                )}
              </div>
              <div className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2">
                <Checkbox
                  ref={selectAll}
                  aria-label="Select all shown scenarios"
                  disabled={listed.length === 0}
                  checked={listed.length > 0 && listedPicked === listed.length}
                  indeterminate={listedPicked > 0 && listedPicked < listed.length}
                  onCheckedChange={(on) =>
                    pick(
                      listed.map((item) => item.id),
                      on,
                    )
                  }
                />
                <span className="text-s-400 text-muted-foreground">
                  {listed.length === items.length
                    ? counted(items.length, "scenario", "scenarios")
                    : `${listed.length} of ${counted(items.length, "scenario", "scenarios")}`}
                </span>
                {shownBatch && (
                  <div className="ml-auto">
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
                  </div>
                )}
              </div>
              {selected.length > 0 && (
                <SelectionBar
                  count={selected.length}
                  personas={personas.data ?? []}
                  assigning={assign.isPending}
                  deleting={remove.isPending}
                  onPersona={assignPersona}
                  onRun={() => setRunning(selected)}
                  onDelete={(close) => deleteScenarios(selected, close)}
                  onClear={() => {
                    setPicked(new Set());
                    selectAll.current?.focus();
                  }}
                />
              )}
              {listed.length === 0 ? (
                <p className="px-4 py-6 text-p-400 text-muted-foreground">
                  No scenarios match the filters.
                </p>
              ) : (
                <ul className="divide-y">
                  {listed.map((item) => (
                    <ScenarioRow
                      key={item.id}
                      scenario={item}
                      persona={personaName(item.persona_id)}
                      open={item.id === open?.id}
                      checked={picked.has(item.id)}
                      fresh={generation.newIds.has(item.id)}
                      onCheck={(on) => pick([item.id], on)}
                      onOpen={() => setOpenId(item.id)}
                    />
                  ))}
                </ul>
              )}
            </div>
            {open && (
              <ScenarioDetail
                key={open.id}
                agent={agent}
                scenario={open}
                persona={personaName(open.persona_id)}
                onEdit={() => setEditing(open)}
                onFork={() => setForking(open)}
                onRun={() => setRunning([open.id])}
              />
            )}
          </div>
        )}
      </Panel>

      {forking && (
        <ScenarioFork
          agent={agent}
          scenario={forking}
          onOpen={(id, fork) => {
            setOpenId(id);
            setEditing(fork ?? null);
          }}
          onClosed={() => setForking(null)}
        />
      )}
      {editing !== null && (
        <ScenarioDialog
          key={scenario?.id ?? "new"}
          agent={agent}
          scenario={scenario}
          onSaved={(saved) => setOpenId(saved.id)}
          onClosed={() => setEditing(null)}
        />
      )}
      {running && (
        <RunDialog agent={agent} scenarioIds={running} onClosed={() => setRunning(null)} />
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

/** The actions for the checked scenarios, in a bar that stays in view at the bottom of the list
 * while it scrolls. It comes first in the page's order, so the keyboard reaches it before the
 * rows. */
function SelectionBar({
  count,
  personas,
  assigning,
  deleting,
  onPersona,
  onRun,
  onDelete,
  onClear,
}: {
  count: number;
  personas: Persona[];
  assigning: boolean;
  deleting: boolean;
  onPersona: (persona: Persona) => void;
  onRun: () => void;
  onDelete: (close: () => void) => void;
  onClear: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  /** Changes to many scenarios at once are capped; a run is limited by the server's own cap. */
  const bulk = count <= MAX_BULK;
  const onInk =
    "text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground aria-expanded:bg-primary-foreground/10";
  return (
    <div
      role="group"
      aria-label="Selected scenarios"
      className={cn(
        "sticky bottom-0 z-10 order-last m-3 flex flex-wrap items-center gap-1 rounded-md bg-primary py-1.5 pr-1.5 pl-3.5 text-primary-foreground shadow-md",
        RISE,
      )}
    >
      <span className="text-s-500 whitespace-nowrap">{count} selected</span>
      <Button
        variant="ghost"
        size="sm"
        className={cn(onInk, "text-primary-foreground/70")}
        onClick={onClear}
      >
        Clear
      </Button>
      <div className="ml-auto flex items-center gap-1">
        {bulk && (
          <>
            <DropdownMenu disabled={assigning || personas.length === 0}>
              <DropdownMenuTrigger
                aria-label="Set the persona of the selected scenarios"
                render={<Button variant="ghost" size="sm" className={onInk} />}
              >
                Persona
                <ChevronDown />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {personas.map((persona) => (
                  <DropdownMenuItem key={persona.id} onClick={() => onPersona(persona)}>
                    {persona.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Delete ${counted(count, "scenario", "scenarios")}`}
              title="Delete"
              className={onInk}
              onClick={() => setConfirming(true)}
            >
              <Trash2 />
            </Button>
          </>
        )}
        <Button variant="outline" size="sm" className="border-transparent" onClick={onRun}>
          <Play />
          Run {count}
        </Button>
      </div>
      {!bulk && (
        <p className="basis-full pb-1 text-xs-400 text-primary-foreground/70">
          Select at most {MAX_BULK} to change or delete them at once.
        </p>
      )}
      <DeleteDialog
        name={counted(count, "scenario", "scenarios")}
        description="Past and queued conversations are not changed."
        pending={deleting}
        open={confirming}
        onOpenChange={setConfirming}
        onDelete={onDelete}
      />
    </div>
  );
}

function ScenarioRow({
  scenario,
  persona,
  open,
  checked,
  fresh,
  onCheck,
  onOpen,
}: {
  scenario: Scenario;
  persona: string;
  open: boolean;
  checked: boolean;
  fresh: boolean;
  onCheck: (on: boolean) => void;
  onOpen: () => void;
}) {
  return (
    <li
      className={cn(
        "flex items-start gap-3 px-4 transition-colors duration-150",
        open ? "bg-muted" : "hover:bg-hv1",
        fresh && RISE,
      )}
    >
      <Checkbox
        className="mt-3.5"
        aria-label={`Select ${scenario.name}`}
        checked={checked}
        onCheckedChange={onCheck}
      />
      <button
        type="button"
        aria-current={open || undefined}
        onClick={onOpen}
        className="grid min-w-0 flex-1 gap-1 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-s-500" title={scenario.name}>
            {scenario.name}
          </span>
          {fresh && <Badge className="shrink-0">New</Badge>}
        </span>
        <span className="flex min-w-0 items-center gap-2 text-xs-400 text-muted-foreground">
          <Badge variant={CATEGORY_BADGE[scenario.category]} className="shrink-0">
            {CATEGORY_LABELS[scenario.category]}
          </Badge>
          <span className="truncate">
            {persona}
            {scenario.caller && ` · ${scenario.caller.model}`}
          </span>
        </span>
      </button>
    </li>
  );
}

/** One scenario as a call plays it: who calls, what the caller knows, and what the judges
 * check. It stays in view while the list scrolls: its height leaves out the shell's 3.5rem
 * header and the 1.25rem padding above and below the page. */
function ScenarioDetail({
  agent,
  scenario,
  persona,
  onEdit,
  onFork,
  onRun,
}: {
  agent: Agent;
  scenario: Scenario;
  persona: string;
  onEdit: () => void;
  onFork: () => void;
  onRun: () => void;
}) {
  const outbound = agent.direction === "outbound";
  const [chosen, setChosen] = useState<string | null>(null);
  const selected =
    scenario.data_sets.find((dataSet) => dataSet.id === chosen) ?? scenario.data_sets[0];
  return (
    <section
      aria-label={scenario.name}
      className="flex min-w-0 flex-col lg:sticky lg:top-0 lg:max-h-[calc(100svh-6rem)] lg:self-start lg:overflow-y-auto"
    >
      <header className="flex flex-wrap items-start gap-4 border-b px-6 py-5">
        <div className="grid min-w-0 flex-1 basis-64 gap-1.5">
          <div className="flex min-w-0 items-start gap-2.5">
            <h2 className="min-w-0 text-h4-500 wrap-anywhere">{scenario.name}</h2>
            <Badge variant={CATEGORY_BADGE[scenario.category]} className="shrink-0">
              {CATEGORY_LABELS[scenario.category]}
            </Badge>
          </div>
          {scenario.description && (
            <p className="text-s-400 text-muted-foreground">{scenario.description}</p>
          )}
          <ForkedFrom kind="scenario" id={scenario.forked_from_id} />
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onFork}>
            <GitFork />
            Fork
          </Button>
          <Button variant="outline" size="sm" onClick={onEdit}>
            <Pencil />
            Edit
          </Button>
          <Button size="sm" onClick={onRun}>
            <Play />
            Run
          </Button>
        </div>
      </header>
      <DataSetTabs scenario={scenario} selected={selected} onSelect={setChosen}>
        <DataSetBar agent={agent} scenario={scenario} selected={selected} onSelect={setChosen} />
        <DataSetPanel scenario={scenario} selected={selected}>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-6 px-6 py-5">
            <Section label="Persona">{persona}</Section>
            {scenario.caller && (
              <Section label="Caller model">
                {scenario.caller.model}
                {scenario.caller.reasoning_effort && `, ${scenario.caller.reasoning_effort} effort`}
              </Section>
            )}
            <Section label="First words">
              {scenario.first_words ?? (
                <span className="text-muted-foreground">
                  The default for the persona's language
                </span>
              )}
            </Section>
            <Section label="Instructions" wide>
              <Filled text={scenario.instructions} facts={selected.known_facts} />
            </Section>
            <Section label="What the caller knows">
              <FactList facts={selected.known_facts} />
            </Section>
            <Section label="What the caller does not have">
              {scenario.unknown_facts.length > 0 ? (
                <ul className="grid gap-1.5 text-s-400">
                  {scenario.unknown_facts.map((fact, index) => (
                    <li key={index}>{fact}</li>
                  ))}
                </ul>
              ) : (
                <span className="text-muted-foreground">None</span>
              )}
            </Section>
            {outbound && (
              <Section label="Data sent to the agent" wide>
                <FactList facts={selected.agent_data} />
              </Section>
            )}
            <Section label="Criteria" wide>
              {scenario.criteria.length > 0 ? (
                <ol className="divide-y rounded-md border">
                  {scenario.criteria.map((criterion, index) => (
                    <li
                      key={index}
                      className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-2 px-3 py-2.5 text-s-400"
                    >
                      <span className="text-muted-foreground tabular-nums">{index + 1}</span>
                      <span>
                        <Filled text={criterion} facts={selected.known_facts} />
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <span className="text-muted-foreground">None</span>
              )}
            </Section>
          </dl>
        </DataSetPanel>
      </DataSetTabs>
      <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-6 py-3 text-xs-400 text-muted-foreground">
        <span>Version {scenario.current_version}</span>
        <span>Updated on {when(scenario.updated_at)}</span>
        <CopyId id={scenario.id} label="scenario id" />
      </footer>
    </section>
  );
}

function Section({
  label,
  wide = false,
  children,
}: {
  label: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={cn("grid min-w-0 content-start gap-2", wide && "col-span-full")}>
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-p-400">{children}</dd>
    </div>
  );
}

function FactList({ facts }: { facts: Fact[] }) {
  if (facts.length === 0) return <span className="text-muted-foreground">None</span>;
  return (
    <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-s-400">
      {facts.map((fact, index) => (
        <Fragment key={index}>
          <dt className="text-muted-foreground">{fact.name}</dt>
          <dd className="wrap-anywhere">{fact.value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
