import { Bot, Copy, Ellipsis, Info, Pencil, Play, Plus, Trash2, TriangleAlert } from "lucide-react";
import { type SubmitEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { DeleteConfirm } from "@/components/confirm-dialogs";
import { Pager } from "@/components/pager";
import { Panel, PanelHeader } from "@/components/panel";
import { ResultLabel } from "@/components/status-label";
import { Timestamp } from "@/components/timestamp";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { FieldError } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { usePageParam } from "@/hooks/use-page-param";
import { copyText } from "@/lib/clipboard";
import { counted } from "@/lib/format";
import { revealErrors } from "@/lib/forms";
import { randomKey } from "@/lib/random-key";
import {
  SUITES_PAGE,
  useDeleteSuite,
  useSaveSuite,
  useScenarioCount,
  useStartSuite,
  useSuite,
  useSuiteRuns,
} from "@/lib/queries";
import { asEntry, passPercentOk, SUITE_CHANGED } from "@/lib/suites";
import type { Suite, SuiteEntryRead, SuiteRunSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { SuiteEntryDialog } from "@/pages/suite-entry-dialog";
import { SuiteFields } from "@/pages/suites";

const ENTRY_COLUMNS =
  "grid grid-cols-1 items-center gap-x-4 gap-y-1 px-5 md:grid-cols-[minmax(0,1fr)_6rem_10rem_4rem_5rem_11rem_2rem]";
const RUN_COLUMNS =
  "grid grid-cols-1 items-center gap-x-4 gap-y-1 px-5 md:grid-cols-[8rem_minmax(0,1fr)_10rem_6rem_9rem]";

/** A suite: its agents, which this page edits, and its runs. */
export function SuitePage() {
  const { id = "" } = useParams();
  const suite = useSuite(id);
  if (suite.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the suite</AlertTitle>
        <AlertDescription>{suite.error.message}</AlertDescription>
      </Alert>
    );
  }
  if (suite.isPending) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-36 w-full rounded-lg" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
    );
  }
  return (
    <div className="grid gap-6">
      <Overview suite={suite.data} />
      <Entries suite={suite.data} />
      <SuiteRuns suite={suite.data} />
    </div>
  );
}

function Overview({ suite }: { suite: Suite }) {
  const [editing, setEditing] = useState(false);
  const [starting, setStarting] = useState(false);
  const broken = suite.entries.filter((entry) => entry.problems.length > 0);
  const command = `yaksh suite run ${suite.id} --wait`;
  const runnable = suite.entries.length > 0 && broken.length === 0;
  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4 px-5 pt-5 pb-4">
        <div className="grid min-w-0 flex-1 basis-72 gap-1">
          <h1 className="truncate text-h3-500" title={suite.name}>
            {suite.name}
          </h1>
          <p className="text-s-400 text-muted-foreground">
            {suite.entries.length === 0
              ? "No agents yet."
              : `${counted(suite.entries.length, "agent", "agents")}, ${counted(suite.calls, "call", "calls")} in each run.`}{" "}
            Required pass rate {suite.required_pass_percent}%.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            <Pencil />
            Edit
          </Button>
          <Button
            size="sm"
            disabled={!runnable}
            title={suite.entries.length === 0 ? "Add an agent first" : undefined}
            onClick={() => setStarting(true)}
          >
            <Play />
            Run suite
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-3 border-t px-5 py-3 text-xs-400">
        <span className="text-muted-foreground">From CLI</span>
        <code className="min-w-0 flex-1 truncate rounded-sm bg-muted px-2.5 py-1 font-mono">
          {command}
        </code>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Copy the command"
          onClick={() => void copyText(command, "Command copied")}
        >
          <Copy />
        </Button>
      </div>
      {broken.length > 0 && (
        <div
          role="status"
          className="flex items-center gap-2 border-t bg-warning px-5 py-2.5 text-s-400 text-warning-foreground"
        >
          <TriangleAlert className="size-4 shrink-0" />
          Fix {counted(broken.length, "agent", "agents")} to run the suite. The CLI and the API
          refuse it too.
        </div>
      )}
      {editing && <EditSuiteDialog suite={suite} onClosed={() => setEditing(false)} />}
      {starting && <RunSuiteDialog suite={suite} onClosed={() => setStarting(false)} />}
    </Panel>
  );
}

function Entries({ suite }: { suite: Suite }) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<SuiteEntryRead | null>(null);
  const phone = suite.entries
    .filter((entry) => entry.transport === "phone")
    .reduce((sum, entry) => sum + entry.calls, 0);
  const text = suite.calls - phone;
  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title={
          <span className="grid gap-0.5">
            Agents
            <span className="text-s-400 font-normal text-muted-foreground">
              Each agent gets its own run, on its newest version.
            </span>
          </span>
        }
        action={
          suite.entries.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              <Plus />
              Add agent
            </Button>
          )
        }
      />
      {suite.entries.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Bot />
            </EmptyMedia>
            <EmptyTitle>No agents yet</EmptyTitle>
            <EmptyDescription>
              Add the agents to test together. For each one, choose the connection and the
              scenarios.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setAdding(true)}>
              <Plus />
              Add agent
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <>
          <div
            className={cn(ENTRY_COLUMNS, "hidden border-b py-3 text-label text-secondary md:grid")}
          >
            <span>Agent</span>
            <span>Connection</span>
            <span>Scenarios</span>
            <span>Calls</span>
            <span>Repeats</span>
            <span>Limits</span>
            <span />
          </div>
          <ul className="divide-y">
            {suite.entries.map((entry) => (
              <EntryRow
                key={entry.position}
                suite={suite}
                entry={entry}
                onEdit={() => setEditing(entry)}
              />
            ))}
          </ul>
          <p className="border-t bg-muted/40 px-5 py-3 text-s-400 text-muted-foreground tabular-nums">
            {counted(suite.calls, "call", "calls")} in each run
            {phone > 0 && text > 0 && `: ${phone} phone, ${text} text`}.
          </p>
        </>
      )}
      {adding && <SuiteEntryDialog suite={suite} onClosed={() => setAdding(false)} />}
      {editing && (
        <SuiteEntryDialog suite={suite} entry={editing} onClosed={() => setEditing(null)} />
      )}
    </Panel>
  );
}

function EntryRow({
  suite,
  entry,
  onEdit,
}: {
  suite: Suite;
  entry: SuiteEntryRead;
  onEdit: () => void;
}) {
  const save = useSaveSuite(suite.id);
  const all = !Array.isArray(entry.scenarios);
  const total = useScenarioCount(entry.agent_id).data;
  const chosen = Array.isArray(entry.scenarios) ? entry.scenarios : [];
  const personas = new Set(chosen.flatMap((item) => item.persona_ids ?? []));
  const dataSets = chosen.reduce((sum, item) => sum + (item.data_set_ids?.length ?? 0), 0);
  const remove = () =>
    save.mutate(
      {
        revision: suite.revision,
        entries: suite.entries.filter((other) => other !== entry).map(asEntry),
      },
      {
        onError: (error) =>
          toast.error(`Could not remove ${entry.agent_name}`, { description: error.message }),
      },
    );
  return (
    <li className={cn(ENTRY_COLUMNS, "py-3.5 text-s-400")}>
      <div className="grid min-w-0 gap-0.5">
        <Link
          to={`/agents/${entry.agent_id}`}
          className="truncate text-s-500 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          {entry.agent_name}
        </Link>
        {entry.problems.map((problem) => (
          <span key={problem} className="flex items-center gap-1.5 text-status-warning-text">
            <TriangleAlert className="size-3.5 shrink-0" />
            {problem}
          </span>
        ))}
      </div>
      <span>{entry.transport === "phone" ? "Phone" : "Text"}</span>
      {all ? (
        <span className="flex items-center gap-1">
          All {entry.scenario_count}
          <Tooltip>
            <TooltipTrigger
              render={
                <button
                  type="button"
                  aria-label="About all scenarios"
                  className="flex size-5 items-center justify-center rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
                />
              }
            >
              <Info className="size-3.5" />
            </TooltipTrigger>
            <TooltipContent className="max-w-72">
              Each run uses all the scenarios that the agent has when the run starts. A scenario
              that you add later is in the next run. A scenario that you delete is not.
            </TooltipContent>
          </Tooltip>
        </span>
      ) : (
        <span className="grid">
          <span>
            {entry.scenario_count}
            {total !== undefined && ` of ${total}`}
          </span>
          <span className="text-muted-foreground">
            {counted(personas.size, "persona", "personas")}
            {dataSets > chosen.length && `, ${counted(dataSets, "data set", "data sets")}`}
          </span>
        </span>
      )}
      <span className="tabular-nums">{entry.calls}</span>
      <span className="tabular-nums">{entry.repeats}</span>
      <span className={limitsText(entry) === "Default" ? "text-muted-foreground" : undefined}>
        {limitsText(entry)}
      </span>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`More actions for ${entry.agent_name}`}
            />
          }
        >
          <Ellipsis />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={onEdit}>
            <Pencil />
            Edit
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" disabled={save.isPending} onClick={remove}>
            <Trash2 />
            Remove from the suite
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}

function limitsText(entry: SuiteEntryRead): string {
  const parts = [
    entry.max_parallel !== null && `${entry.max_parallel} at once`,
    entry.start_interval_s !== null && `${entry.start_interval_s} s apart`,
    entry.max_duration_s !== null && `${entry.max_duration_s} s each`,
    entry.max_turns !== null && counted(entry.max_turns, "turn", "turns"),
    entry.max_retries !== null && counted(entry.max_retries, "retry", "retries"),
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "Default";
}

function SuiteRuns({ suite }: { suite: Suite }) {
  const page = usePageParam();
  const runs = useSuiteRuns(suite.id, page);
  if (runs.data?.total === 0 && page === 1) return null;
  return (
    <Panel className="overflow-hidden">
      <PanelHeader title="Runs of this suite" />
      <div className={cn(RUN_COLUMNS, "hidden border-b py-3 text-label text-secondary md:grid")}>
        <span>Result</span>
        <span>Started</span>
        <span>Agents</span>
        <span>Calls</span>
        <span>Ended</span>
      </div>
      {runs.isError ? (
        <p role="alert" className="px-5 py-4 text-destructive">
          Could not load the runs: {runs.error.message}
        </p>
      ) : (
        <ul className="divide-y">
          {runs.data === undefined ? (
            <li className="px-5 py-3.5">
              <Skeleton className="h-10" />
            </li>
          ) : (
            runs.data.items.map((suiteRun) => <SuiteRunRow key={suiteRun.id} suiteRun={suiteRun} />)
          )}
        </ul>
      )}
      <Pager className="px-5 py-3" query={runs} pageSize={SUITES_PAGE} />
    </Panel>
  );
}

function SuiteRunRow({ suiteRun }: { suiteRun: SuiteRunSummary }) {
  const final = !["running", "judging"].includes(suiteRun.result);
  return (
    <li
      className={cn(
        RUN_COLUMNS,
        "relative py-3.5 text-s-400 transition-colors duration-150 hover:bg-hv1 has-[a:focus-visible]:bg-hv1 has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring/50 has-[a:focus-visible]:ring-inset",
      )}
    >
      <ResultLabel result={suiteRun.result} />
      <Link
        to={`/suite-runs/${suiteRun.id}`}
        className="text-s-500 outline-none after:absolute after:inset-0"
      >
        <Timestamp iso={suiteRun.created_at} />
      </Link>
      <span className="text-muted-foreground">
        {suiteRun.result === "cancelled"
          ? "Cancelled"
          : final
            ? `${suiteRun.passed_run_count} of ${suiteRun.run_count} passed`
            : counted(suiteRun.run_count, "run", "runs")}
      </span>
      <span className="tabular-nums">{suiteRun.conversation_count}</span>
      <span className="text-muted-foreground">
        {suiteRun.ended_at ? <Timestamp iso={suiteRun.ended_at} /> : "Not yet"}
      </span>
    </li>
  );
}

function EditSuiteDialog({ suite, onClosed }: { suite: Suite; onClosed: () => void }) {
  const [open, setOpen] = useState(true);
  // The revision that the fields were read at: a save over a newer change gets a 409.
  const [revision] = useState(suite.revision);
  const [name, setName] = useState(suite.name);
  const [percent, setPercent] = useState(String(suite.required_pass_percent));
  const [submitted, setSubmitted] = useState(false);
  const save = useSaveSuite(suite.id);
  const remove = useDeleteSuite(suite.id);
  const navigate = useNavigate();
  const stale = suite.revision !== revision && !save.isSuccess;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const ok = Boolean(name.trim()) && passPercentOk(percent);
    if (!revealErrors(event.currentTarget, () => setSubmitted(true), ok)) return;
    save.mutate(
      { revision, name: name.trim(), required_pass_percent: Number(percent) },
      { onSuccess: () => setOpen(false) },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !save.isPending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="sm:max-w-md">
        <form noValidate onSubmit={submit} className="grid gap-6">
          <DialogHeader>
            <DialogTitle>Edit suite</DialogTitle>
            <DialogDescription>
              A new pass rate counts for the next suite runs. A suite run keeps the rate it started
              with.
            </DialogDescription>
          </DialogHeader>
          <SuiteFields
            name={name}
            percent={percent}
            submitted={submitted}
            onNameChange={setName}
            onPercentChange={setPercent}
          />
          {stale ? (
            <FieldError>{SUITE_CHANGED}</FieldError>
          ) : (
            save.isError && <FieldError>{save.error.message}</FieldError>
          )}
          {remove.isError && <FieldError>{remove.error.message}</FieldError>}
          <DialogFooter>
            <DeleteConfirm
              name={suite.name}
              label="Delete suite"
              description="Its suite runs and their runs stay. A suite with a run at work cannot be deleted."
              pending={remove.isPending}
              onDelete={(close) =>
                remove.mutate(undefined, {
                  onSettled: close,
                  onSuccess: () => navigate("/suites"),
                })
              }
            />
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending || stale}>
              {save.isPending && <Spinner />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Asks before a suite run starts: it can make many paid phone calls. */
export function RunSuiteDialog({ suite, onClosed }: { suite: Suite; onClosed: () => void }) {
  const [open, setOpen] = useState(true);
  const [requestKey] = useState(randomKey);
  const start = useStartSuite(suite.id, requestKey);
  const navigate = useNavigate();
  const phone = suite.entries
    .filter((entry) => entry.transport === "phone")
    .reduce((sum, entry) => sum + entry.calls, 0);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && !start.isPending && setOpen(false)}
      onOpenChangeComplete={(next) => !next && onClosed()}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Run {suite.name}</DialogTitle>
          <DialogDescription>
            {counted(suite.entries.length, "run starts", "runs start")} now, one for each agent.
          </DialogDescription>
        </DialogHeader>
        <dl className="grid">
          {[
            ["Phone calls", phone],
            ["Text conversations", suite.calls - phone],
            ["Required pass rate", `${suite.required_pass_percent}%`],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between border-t py-2 text-s-400">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        {start.isError && <FieldError>{start.error.message}</FieldError>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={start.isPending}
            onClick={() =>
              start.mutate(undefined, {
                onSuccess: (suiteRun) => navigate(`/suite-runs/${suiteRun.id}`),
              })
            }
          >
            {start.isPending && <Spinner />}
            Start {counted(suite.calls, "call", "calls")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
