import { Link } from "react-router";

import { Pager } from "@/components/pager";
import { Panel, PanelHeader } from "@/components/panel";
import { RelativeTime } from "@/components/relative-time";
import { RunStatusBadge } from "@/components/status-dot";
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
    <Panel className="overflow-hidden">
      <PanelHeader title="Runs" />
      {runs.isPending ? (
        <div className="grid gap-3 p-5">
          <Skeleton className="h-10" />
        </div>
      ) : runs.isError ? (
        <p className="px-5 py-4 text-sm text-destructive">{runs.error.message}</p>
      ) : runs.data.items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-muted-foreground">
          No runs yet. Select scenarios above and click Run.
        </p>
      ) : (
        <ul className="divide-y">
          {runs.data.items.map((run) => (
            <li key={run.id}>
              <Link
                to={`/runs/${run.id}`}
                className="grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-x-4 px-5 py-3 outline-none transition-colors duration-150 hover:bg-foreground/[0.025] focus-visible:bg-foreground/[0.04] focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
              >
                <span className="text-sm">
                  <RunStatusBadge status={run.status} />
                </span>
                <span className="grid min-w-0 gap-0.5 text-sm">
                  <span className="truncate font-medium">{runTitle(run)}</span>
                  <span className="truncate text-muted-foreground">{progress(run)}</span>
                </span>
                <span className="text-right text-sm text-muted-foreground">
                  <RelativeTime iso={run.created_at} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Pager className="border-t px-5 py-3" query={runs} pageSize={RUNS_PAGE} />
    </Panel>
  );
}
