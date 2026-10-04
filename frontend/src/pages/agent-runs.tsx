import { Link } from "react-router";

import { Pager } from "@/components/pager";
import { ActionPanel } from "@/components/panel";
import { RelativeTime } from "@/components/relative-time";
import { RunStatusLabel } from "@/components/status-label";
import { Skeleton } from "@/components/ui/skeleton";
import { usePageParam } from "@/hooks/use-page-param";
import { counted, runTitle, runTotal } from "@/lib/format";
import { RUNS_PAGE, useRuns } from "@/lib/queries";
import { type Agent, OUTCOME_GROUPS, type RunSummary } from "@/lib/types";

function progress(run: RunSummary): string {
  const parts = OUTCOME_GROUPS.filter((group) => run.counts[group.value] > 0).map(
    (group) => `${group.label.toLowerCase()} ${run.counts[group.value]}`,
  );
  return `${counted(runTotal(run), "conversation", "conversations")}: ${parts.join(", ")}`;
}

export function AgentRuns({ agent }: { agent: Agent }) {
  const runs = useRuns(agent.id, usePageParam());
  return (
    <ActionPanel>
      {runs.isPending ? (
        <div className="grid gap-3 p-5">
          <Skeleton className="h-10" />
        </div>
      ) : runs.isError ? (
        <p role="alert" className="px-5 py-4 text-sm text-destructive">
          {runs.error.message}
        </p>
      ) : runs.data.items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-muted-foreground">
          No runs yet. Select scenarios on the Scenarios tab and click Run.
        </p>
      ) : (
        <ul className="divide-y">
          {runs.data.items.map((run) => (
            <li key={run.id}>
              <Link
                to={`/runs/${run.id}`}
                title={runTitle(run)}
                className="grid grid-cols-[6.5rem_minmax(0,1fr)_auto] group items-center gap-x-4 px-5 py-3.5 outline-none transition-colors duration-150 hover:bg-muted/60 active:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
              >
                <span className="text-sm">
                  <RunStatusLabel status={run.status} />
                </span>
                <span className="grid min-w-0 gap-0.5 text-s-400">
                  <span className="truncate text-s-500 transition-colors group-hover:text-brand-text">
                    {runTitle(run)}
                  </span>
                  <span className="truncate text-muted-foreground">{progress(run)}</span>
                </span>
                <span className="text-right font-mono text-xs-400 text-muted-foreground">
                  <RelativeTime iso={run.created_at} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Pager className="border-t px-5 py-3" query={runs} pageSize={RUNS_PAGE} />
    </ActionPanel>
  );
}
