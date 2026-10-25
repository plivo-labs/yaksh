import { ChevronDown, Layers, Play, Plus, Square } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { ConversationList } from "@/components/conversation-list";
import { CopyId } from "@/components/copy-id";
import { Pager } from "@/components/pager";
import { Panel, PanelHeader } from "@/components/panel";
import { RunMetricsPanel } from "@/components/run-metrics";
import { RunVerdictsPanel } from "@/components/run-verdicts";
import { RunStatusLabel } from "@/components/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useFilterParams } from "@/hooks/use-filter-params";
import { ANSWERS } from "@/lib/answering";
import { usePageParam } from "@/hooks/use-page-param";
import { duration, runFinished, runTitle, runTotal, when } from "@/lib/format";
import {
  CONVERSATIONS_PAGE,
  useAgent,
  useAllSuites,
  useCancelRun,
  useConversations,
  useRun,
  useSuite,
} from "@/lib/queries";
import {
  ACTIVE_RUN_STATUSES,
  END_REASON_LABELS,
  type EndReason,
  OUTCOME_GROUPS,
  type OutcomeGroup,
  type Run,
  WAITING_REASON_TEXT,
} from "@/lib/types";
import { RunDialog } from "@/pages/run-dialog";
import { SuiteEntryDialog } from "@/pages/suite-entry-dialog";
import { NewSuiteDialog } from "@/pages/suites";

export function RunPage() {
  const { id = "" } = useParams();
  const run = useRun(id);

  if (run.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the run</AlertTitle>
        <AlertDescription>{run.error.message}</AlertDescription>
      </Alert>
    );
  }
  if (run.isPending) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-56 w-full rounded-lg" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
    );
  }
  const data = run.data;

  return (
    <div className="grid gap-6">
      <Overview run={data} />
      <RunVerdictsPanel
        runId={data.id}
        agentId={data.agent_id}
        active={ACTIVE_RUN_STATUSES.includes(data.status)}
      />
      <RunMetricsPanel
        runId={data.id}
        text={data.transport === "text"}
        active={ACTIVE_RUN_STATUSES.includes(data.status)}
      />
      <Conversations run={data} />
    </div>
  );
}

function Overview({ run }: { run: Run }) {
  const total = runTotal(run);
  const finished = runFinished(run);
  const running = run.counts.in_progress;
  const share = (count: number) => `${total ? (count / total) * 100 : 0}%`;
  const endReasons = Object.entries(run.end_reasons) as [EndReason, number][];
  return (
    <Panel>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4 px-5 pt-5 pb-4">
        <div className="grid min-w-0 flex-1 basis-72 gap-1">
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="truncate text-h3-500" title={runTitle(run)}>
              {runTitle(run)}
            </h1>
            <RunStatusLabel status={run.status} />
          </div>
          <p className="text-s-400 text-muted-foreground">
            <Link
              to={`/agents/${run.agent_id}`}
              className="rounded-sm underline decoration-muted-foreground/40 underline-offset-4 outline-none hover:text-foreground hover:decoration-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              {run.agent_name}
            </Link>
            , version {run.agent_version}
            {run.started_at && `, started ${when(run.started_at)}`}
            {run.ended_at && `, ended ${when(run.ended_at)}`}
          </p>
          {run.waiting_reason && (
            <p className="text-s-400 text-muted-foreground">
              Waiting: {WAITING_REASON_TEXT[run.waiting_reason]}
            </p>
          )}
          {run.suite_run && (
            <p className="flex items-center gap-1.5 text-s-400 text-muted-foreground">
              <Layers className="size-3.5" />
              Part of a suite run of{" "}
              <Link
                to={`/suite-runs/${run.suite_run.id}`}
                className="text-brand-text underline-offset-4 hover:underline"
              >
                {run.suite_run.suite_name}
              </Link>
            </p>
          )}
        </div>
        <RunActions run={run} />
      </div>
      <div className="grid gap-3 border-t px-5 py-4">
        <div className="flex items-baseline justify-between text-p-400">
          <span className="tabular-nums">
            <span className="font-medium">
              {finished} of {total} finished
            </span>
            {running > 0 && <span className="text-muted-foreground">, {running} in progress</span>}
          </span>
          {run.retries > 0 && (
            <span className="text-muted-foreground tabular-nums">
              {run.retries} {run.retries === 1 ? "retry" : "retries"}
            </span>
          )}
        </div>
        <div
          role="progressbar"
          aria-label="Finished conversations"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={finished}
          className="flex h-1.5 overflow-hidden rounded-sm bg-muted"
        >
          <div
            className="h-full bg-primary transition-[width] duration-300 ease-out"
            style={{ width: share(finished) }}
          />
          {running > 0 && (
            <div
              className="h-full bar-shimmer transition-[width] duration-300 ease-out"
              style={{ width: share(running) }}
            />
          )}
        </div>
        <GroupFilter run={run} />
        <AnswerFilter run={run} />
        {endReasons.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs-400">
            <span className="mr-1 text-muted-foreground">How conversations ended</span>
            {endReasons.map(([reason, count]) => (
              <Badge key={reason} variant="tag">
                {END_REASON_LABELS[reason]} · {count}
              </Badge>
            ))}
          </div>
        )}
      </div>
      <dl className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t px-5 py-3 text-xs-400">
        <Setting label="Repeats">{run.repeats}</Setting>
        <Setting label="Limits">
          {run.max_duration_s} s, {run.max_turns} turns
        </Setting>
        <Setting label="At once">{run.max_parallel ?? "No run limit"}</Setting>
        <Setting label="Delay">
          {run.start_interval_s === null ? "None" : `${run.start_interval_s} s`}
        </Setting>
        <Setting label="Retries">Up to {run.max_retries}</Setting>
        <Setting label="Median talk">{duration(run.median_talk_ms) || "None yet"}</Setting>
        <Setting label="Run id">
          <CopyId id={run.id} label="run id" />
        </Setting>
      </dl>
    </Panel>
  );
}

function Setting({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  );
}

function RunActions({ run }: { run: Run }) {
  const cancel = useCancelRun(run.id);
  const [again, setAgain] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const agent = useAgent(run.agent_id);
  const active = ACTIVE_RUN_STATUSES.includes(run.status);
  return (
    <div className="grid justify-items-end gap-2">
      <div className="flex gap-2">
        {active && run.status !== "cancelling" && (
          <Button variant="outline" size="sm" onClick={() => setCancelling(true)}>
            <Square />
            Cancel run
          </Button>
        )}
        <AlertDialog open={cancelling} onOpenChange={setCancelling}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Cancel this run?</AlertDialogTitle>
              <AlertDialogDescription>
                Conversations that have not started are cancelled. Running conversations end, and
                what was said so far is kept. No conversation is tried again.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep running</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                disabled={cancel.isPending}
                onClick={() =>
                  cancel.mutate(undefined, {
                    onSuccess: () => setCancelling(false),
                    onError: (error) =>
                      toast.error("Could not cancel the run", { description: error.message }),
                  })
                }
              >
                {cancel.isPending && <Spinner />}
                Cancel run
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        <AddToSuite run={run} disabled={!agent.data} />
        <Button variant="outline" size="sm" disabled={!agent.data} onClick={() => setAgain(true)}>
          <Play />
          Run again
        </Button>
      </div>
      {again && agent.data && (
        <RunDialog
          agent={agent.data}
          scenarioIds={run.scenarios.map((item) => item.scenario_id)}
          personasOf={Object.fromEntries(
            run.scenarios.map((item) => [item.scenario_id, item.persona_ids ?? []]),
          )}
          dataSetsOf={Object.fromEntries(
            run.scenarios.map((item) => [item.scenario_id, item.data_set_ids ?? []]),
          )}
          answersOf={Object.fromEntries(
            run.scenarios.map((item) => [item.scenario_id, item.answered_by ?? []]),
          )}
          earlier={run}
          onClosed={() => setAgain(false)}
        />
      )}
    </div>
  );
}

/** Copies the run's settings into a suite, as a new agent of it: one of the suites, or a new
 * one. The suite does not use the run's results. */
function AddToSuite({ run, disabled }: { run: Run; disabled: boolean }) {
  const suites = useAllSuites();
  const [suiteId, setSuiteId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button variant="outline" size="sm" disabled={disabled} />}>
          <Layers />
          Add to suite
          <ChevronDown />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Copy this run into a suite</DropdownMenuLabel>
            {(suites.data ?? []).map((suite) => (
              <DropdownMenuItem key={suite.id} onClick={() => setSuiteId(suite.id)}>
                {suite.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setCreating(true)}>
            <Plus />
            New suite
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {creating && (
        <NewSuiteDialog
          onCreated={(suite) => setSuiteId(suite.id)}
          onClosed={() => setCreating(false)}
        />
      )}
      {suiteId && <CopyToSuite suiteId={suiteId} run={run} onClosed={() => setSuiteId(null)} />}
    </>
  );
}

function CopyToSuite({
  suiteId,
  run,
  onClosed,
}: {
  suiteId: string;
  run: Run;
  onClosed: () => void;
}) {
  const suite = useSuite(suiteId);
  const navigate = useNavigate();
  const failed = suite.error?.message;
  useEffect(() => {
    if (failed === undefined) return;
    toast.error("Could not load the suite", { description: failed });
    onClosed();
  }, [failed, onClosed]);
  return suite.data ? (
    <SuiteEntryDialog
      suite={suite.data}
      copyRun={run}
      onSaved={() => navigate(`/suites/${suiteId}`)}
      onClosed={onClosed}
    />
  ) : null;
}

function GroupFilter({ run }: { run: Run }) {
  const [params, update] = useFilterParams();
  const chosen = params.get("group");
  const choose = (group: OutcomeGroup) => update({ group: chosen === group ? null : group });
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Show conversations by outcome">
      {OUTCOME_GROUPS.map((group) => (
        <Button
          key={group.value}
          type="button"
          variant={chosen === group.value ? "tertiary" : "ghost"}
          size="sm"
          aria-pressed={chosen === group.value}
          onClick={() => choose(group.value)}
          className="tabular-nums"
        >
          {group.label}
          <span className={chosen === group.value ? undefined : "text-muted-foreground"}>
            {run.counts[group.value]}
          </span>
        </Button>
      ))}
    </div>
  );
}

/** Shown when a voicemail or call screener answered any call of the run. */
function AnswerFilter({ run }: { run: Run }) {
  const [params, update] = useFilterParams();
  const chosen = params.get("answered_by");
  const answers = ANSWERS.filter((answer) => run.answered_by[answer.value]);
  if (answers.every((answer) => answer.value === "caller")) return null;
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label="Show conversations by who answered"
    >
      <span className="mr-1 text-xs-400 text-muted-foreground">Who answered</span>
      {answers.map((answer) => (
        <Button
          key={answer.value}
          type="button"
          variant={chosen === answer.value ? "tertiary" : "ghost"}
          size="sm"
          aria-pressed={chosen === answer.value}
          onClick={() => update({ answered_by: chosen === answer.value ? null : answer.value })}
          className="tabular-nums"
        >
          {answer.label}
          <span className={chosen === answer.value ? undefined : "text-muted-foreground"}>
            {run.answered_by[answer.value]}
          </span>
        </Button>
      ))}
    </div>
  );
}

function Conversations({ run }: { run: Run }) {
  const [params, update] = useFilterParams();
  const group = params.get("group");
  const answeredBy = params.get("answered_by");
  const sort = params.get("sort") ?? "created_at";
  const sortBy = (next: string) => update({ sort: next });
  const conversations = useConversations(
    {
      run_id: run.id,
      latest_attempts: "true",
      sort,
      ...(group ? { group } : {}),
      ...(answeredBy ? { answered_by: answeredBy } : {}),
    },
    usePageParam(),
    { live: ACTIVE_RUN_STATUSES.includes(run.status) },
  );
  const shown = [
    OUTCOME_GROUPS.find((item) => item.value === group)?.label,
    ANSWERS.find((item) => item.value === answeredBy)?.label,
  ]
    .filter(Boolean)
    .map((label) => label?.toLowerCase())
    .join(", ");

  return (
    <Panel className="overflow-hidden">
      <PanelHeader title={shown ? `Conversations: ${shown}` : "Conversations"} />
      <p className="border-b px-5 py-2.5 text-xs-400 text-muted-foreground">
        The latest attempt of each repeat of each scenario. Open a retry to see the attempt before
        it.
      </p>
      <ConversationList
        query={conversations}
        place="panel"
        empty="No conversations in this group."
        sort={{ value: sort, onSort: sortBy }}
      />
      <Pager className="border-t px-5 py-3" query={conversations} pageSize={CONVERSATIONS_PAGE} />
    </Panel>
  );
}
