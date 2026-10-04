import { ChevronLeft, Play, Square } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { toast } from "sonner";

import { ConversationList } from "@/components/conversation-list";
import { Pager } from "@/components/pager";
import { Fact, Panel, PanelHeader } from "@/components/panel";
import { RunStatusBadge } from "@/components/status-dot";
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
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePageParam } from "@/hooks/use-page-param";
import { duration, noiseLabel, runTitle, runTotal, seconds, when } from "@/lib/format";
import {
  CONVERSATIONS_PAGE,
  useAgent,
  useCancelRun,
  useConversations,
  useRun,
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

const FINISHED: OutcomeGroup[] = ["completed", "did_not_connect", "error", "cancelled"];

export function RunPage() {
  const { id = "" } = useParams();
  const run = useRun(id);
  const agent = useAgent(run.data?.agent_id);

  if (run.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the run</AlertTitle>
        <AlertDescription>{run.error.message}</AlertDescription>
      </Alert>
    );
  }
  if (run.isPending) return <Skeleton className="h-96 w-full rounded-lg" />;
  const data = run.data;

  return (
    <div className="grid gap-6">
      <Link
        to={`/agents/${data.agent_id}`}
        className="inline-flex w-fit items-center gap-1 rounded-sm text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <ChevronLeft className="size-4" />
        {agent.data?.name ?? data.agent_name}
      </Link>
      <Overview run={data} />
      <Conversations run={data} />
    </div>
  );
}

function Overview({ run }: { run: Run }) {
  const total = runTotal(run);
  const finished = FINISHED.reduce((sum, group) => sum + run.counts[group], 0);
  const endReasons = Object.entries(run.end_reasons) as [EndReason, number][];
  return (
    <Panel>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4 px-5 pt-5 pb-4">
        <div className="grid min-w-0 flex-1 basis-72 gap-1">
          <div className="flex items-center gap-3">
            <h1 className="truncate text-2xl font-semibold tracking-[-0.015em]">{runTitle(run)}</h1>
            <RunStatusBadge status={run.status} />
          </div>
          <p className="text-sm text-muted-foreground">
            {run.agent_name}, version {run.agent_version}
            {run.started_at && `, started ${when(run.started_at)}`}
            {run.ended_at && `, ended ${when(run.ended_at)}`}
          </p>
          {run.waiting_reason && (
            <p className="text-sm text-muted-foreground">
              Waiting: {WAITING_REASON_TEXT[run.waiting_reason]}
            </p>
          )}
        </div>
        <RunActions run={run} />
      </div>
      <div className="grid gap-3 border-t px-5 py-4">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium tabular-nums">
            {finished} of {total} finished
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
          className="h-1.5 overflow-hidden rounded-full bg-muted"
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
            style={{ width: `${total ? (finished / total) * 100 : 0}%` }}
          />
        </div>
        <GroupFilter run={run} />
      </div>
      <dl className="grid grid-cols-2 gap-4 border-t px-5 py-4 sm:grid-cols-3 lg:grid-cols-9">
        <Fact label="Repeats">{run.repeats}</Fact>
        <Fact label="Time limit">{run.max_duration_s} seconds</Fact>
        <Fact label="Turn limit">{run.max_turns} turns</Fact>
        <Fact label="Background noise">
          {run.background_noise
            ? (noiseLabel(run.background_noise) ?? "None")
            : "Each persona's setting"}
        </Fact>
        <Fact label="Max parallel">{run.max_parallel ?? "No run limit"}</Fact>
        <Fact label="Delay between calls">
          {run.start_interval_s === null ? "None" : `${run.start_interval_s} seconds`}
        </Fact>
        <Fact label="Retries">Up to {run.max_retries}</Fact>
        <Fact label="Median talk time">{duration(run.median_talk_ms) || "None yet"}</Fact>
        <Fact label="Response p50 / p90">
          {run.response_p50_ms === null || run.response_p90_ms === null
            ? "None yet"
            : `${seconds(run.response_p50_ms)} / ${seconds(run.response_p90_ms)}`}
        </Fact>
        <div className="col-span-2 grid min-w-0 gap-0.5 sm:col-span-3 lg:col-span-9">
          <dt className="text-xs text-muted-foreground">End reasons</dt>
          <dd className="text-sm font-medium">
            {endReasons.length === 0
              ? "None yet"
              : endReasons
                  .map(([reason, count]) => `${END_REASON_LABELS[reason]} ${count}`)
                  .join(", ")}
          </dd>
        </div>
      </dl>
    </Panel>
  );
}

function RunActions({ run }: { run: Run }) {
  const cancel = useCancelRun(run.id);
  const [again, setAgain] = useState(false);
  const agent = useAgent(run.agent_id);
  const active = ACTIVE_RUN_STATUSES.includes(run.status);
  return (
    <div className="grid justify-items-end gap-2">
      <div className="flex gap-2">
        {active && run.status !== "cancelling" && (
          <AlertDialog>
            <AlertDialogTrigger render={<Button variant="outline" />}>
              <Square />
              Cancel run
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Cancel this run?</AlertDialogTitle>
                <AlertDialogDescription>
                  Conversations that have not started are cancelled. Calls on the line end, and what
                  was said so far is kept. No conversation is tried again.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep running</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() =>
                    cancel.mutate(undefined, {
                      onError: (error) =>
                        toast.error("Could not cancel the run", { description: error.message }),
                    })
                  }
                >
                  Cancel run
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
        <Button variant="outline" disabled={!agent.data} onClick={() => setAgain(true)}>
          <Play />
          Run again
        </Button>
      </div>
      {again && agent.data && (
        <RunDialog
          agent={agent.data}
          scenarioIds={run.scenario_ids}
          earlier={run}
          onClosed={() => setAgain(false)}
        />
      )}
    </div>
  );
}

function GroupFilter({ run }: { run: Run }) {
  const [params, setParams] = useSearchParams();
  const chosen = params.get("group");
  const choose = (group: OutcomeGroup) => {
    const next = new URLSearchParams(params);
    if (chosen === group) next.delete("group");
    else next.set("group", group);
    next.delete("page");
    setParams(next, { replace: true });
  };
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Show conversations by outcome">
      {OUTCOME_GROUPS.map((group) => (
        <Button
          key={group.value}
          type="button"
          variant={chosen === group.value ? "secondary" : "ghost"}
          size="sm"
          aria-pressed={chosen === group.value}
          onClick={() => choose(group.value)}
          className="tabular-nums"
        >
          {group.label}
          <span className="text-muted-foreground">{run.counts[group.value]}</span>
        </Button>
      ))}
    </div>
  );
}

function Conversations({ run }: { run: Run }) {
  const [params, setParams] = useSearchParams();
  const group = params.get("group");
  const sort = params.get("sort") ?? "created_at";
  const sortBy = (next: string) => {
    const changed = new URLSearchParams(params);
    changed.set("sort", next);
    changed.delete("page");
    setParams(changed, { replace: true });
  };
  const conversations = useConversations(
    {
      run_id: run.id,
      latest_attempts: "true",
      sort,
      ...(group ? { group } : {}),
    },
    usePageParam(),
    { live: ACTIVE_RUN_STATUSES.includes(run.status) },
  );
  const groupLabel = OUTCOME_GROUPS.find((item) => item.value === group)?.label;

  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title={groupLabel ? `Conversations: ${groupLabel.toLowerCase()}` : "Conversations"}
      />
      <p className="border-b px-5 py-2.5 text-xs text-muted-foreground">
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
