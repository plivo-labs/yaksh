import { Link } from "react-router";

import { Timestamp } from "@/components/timestamp";
import { ResponseTime } from "@/components/response-time";
import { RunStatusLabel } from "@/components/status-label";
import { Skeleton } from "@/components/ui/skeleton";
import { counted, runFinished, runTitle, runTotal } from "@/lib/format";
import { ACTIVE_RUN_STATUSES, OUTCOME_GROUPS, type Page, type RunSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Columns follow the list's own width, not the window's: the same list sits in a full page
 * and in a narrow panel. */
const COLUMNS = {
  withAgent:
    "grid grid-cols-1 items-center gap-x-4 gap-y-1 @3xl/runs:grid-cols-[6.5rem_minmax(0,2fr)_minmax(0,1fr)_6rem_7rem_8rem_8rem]",
  withoutAgent:
    "grid grid-cols-1 items-center gap-x-4 gap-y-1 @3xl/runs:grid-cols-[6.5rem_minmax(0,2fr)_6rem_7rem_8rem_8rem]",
};
const GUTTER = { page: "px-3", panel: "px-5" };

function outcomes(run: RunSummary): string {
  const parts = OUTCOME_GROUPS.filter((group) => run.counts[group.value] > 0).map(
    (group) => `${group.label.toLowerCase()} ${run.counts[group.value]}`,
  );
  return `${counted(runTotal(run), "conversation", "conversations")}: ${parts.join(", ")}`;
}

/** Runs, newest first, one row each. `place` sets the edges: a list on a page closes with a
 * border, a list in a panel uses the panel's. */
export function RunList({
  query,
  empty,
  place,
  showAgent = false,
}: {
  query: {
    data?: Page<RunSummary>;
    error: Error | null;
    isFetching: boolean;
    isPlaceholderData: boolean;
  };
  empty: string;
  place: "page" | "panel";
  showAgent?: boolean;
}) {
  const grid = cn(showAgent ? COLUMNS.withAgent : COLUMNS.withoutAgent, GUTTER[place]);
  if (query.error) {
    return (
      <p role="alert" className={cn(GUTTER[place], "py-4 text-p-400 text-destructive")}>
        Could not load the runs: {query.error.message}
      </p>
    );
  }
  return (
    <div
      aria-busy={query.isFetching}
      className={cn(
        "@container/runs transition-opacity duration-150",
        query.isPlaceholderData && "opacity-60",
      )}
    >
      <div
        className={cn(grid, "hidden border-b py-3 text-s-500 text-muted-foreground @3xl/runs:grid")}
      >
        <span>Status</span>
        <span>Run</span>
        {showAgent && <span>Agent</span>}
        <span>Finished</span>
        <span>Response p90</span>
        <span>Started</span>
        <span>Ended</span>
      </div>
      <ul className={cn("divide-y", place === "page" && "border-b")}>
        {query.data === undefined ? (
          [0, 1, 2].map((index) => (
            <li key={index} className={cn(grid, "py-3.5")}>
              <Skeleton className="col-span-full h-10" />
            </li>
          ))
        ) : query.data.items.length === 0 ? (
          <li className={cn(GUTTER[place], "py-6 text-p-400 text-muted-foreground")}>{empty}</li>
        ) : (
          query.data.items.map((run) => (
            <RunRow key={run.id} run={run} grid={grid} showAgent={showAgent} />
          ))
        )}
      </ul>
    </div>
  );
}

function RunRow({ run, grid, showAgent }: { run: RunSummary; grid: string; showAgent: boolean }) {
  const finished = `${runFinished(run)} of ${runTotal(run)}`;
  const started = run.started_at ? (
    <Timestamp iso={run.started_at} />
  ) : ACTIVE_RUN_STATUSES.includes(run.status) ? (
    "Not yet"
  ) : (
    "Never"
  );
  const ended = run.ended_at ? (
    <Timestamp iso={run.ended_at} />
  ) : ACTIVE_RUN_STATUSES.includes(run.status) ? (
    "Not yet"
  ) : (
    "Never"
  );
  return (
    <li
      className={cn(
        grid,
        "group relative py-3.5 transition-colors duration-150 hover:bg-hv1 has-[a:active]:bg-st2 has-[a:focus-visible]:bg-hv1 has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring/50 has-[a:focus-visible]:ring-inset",
      )}
    >
      <div>
        <RunStatusLabel status={run.status} />
      </div>
      <div className="grid min-w-0 gap-0.5">
        <Link
          to={`/runs/${run.id}`}
          aria-label={label(run)}
          title={runTitle(run)}
          className="truncate text-s-500 outline-none transition-colors after:absolute after:inset-0"
        >
          {runTitle(run)}
        </Link>
        <span className="truncate text-s-400 text-muted-foreground">{outcomes(run)}</span>
        <span className="truncate text-s-400 text-muted-foreground @3xl/runs:hidden">
          {finished} finished,{" "}
          {run.started_at ? (
            <>
              started <Timestamp iso={run.started_at} />
            </>
          ) : (
            "not started"
          )}
          {run.ended_at && (
            <>
              , ended <Timestamp iso={run.ended_at} />
            </>
          )}
        </span>
      </div>
      {showAgent && (
        <div className="min-w-0 text-s-400">
          <Link
            to={`/agents/${run.agent_id}`}
            title={run.agent_name}
            className="relative z-10 block w-fit max-w-full truncate rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {run.agent_name}
          </Link>
          <span className="text-muted-foreground">version {run.agent_version}</span>
        </div>
      )}
      <div className="hidden text-xs-400 tabular-nums @3xl/runs:block">{finished}</div>
      <div className="hidden text-s-400 @3xl/runs:block">
        {run.response_p90_ms !== null && <ResponseTime ms={run.response_p90_ms} />}
      </div>
      <div className="hidden text-xs-400 text-muted-foreground @3xl/runs:block">{started}</div>
      <div className="hidden text-xs-400 text-muted-foreground @3xl/runs:block">{ended}</div>
    </li>
  );
}

/** The run with what tells it from the others in the list: two runs can share a name or a
 * start minute, so the id ends it. */
function label(run: RunSummary): string {
  return [
    runTitle(run),
    `${run.agent_name}, version ${run.agent_version}`,
    run.status,
    `${runFinished(run)} of ${runTotal(run)} finished`,
    `id ${run.id.slice(-8)}`,
  ].join(", ");
}
