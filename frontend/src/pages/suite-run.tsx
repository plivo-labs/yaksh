import { Play, Square } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialogs";
import { Panel, PanelHeader } from "@/components/panel";
import { ResultLabel, RunStatusLabel } from "@/components/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { counted, percent, runFinished, runTotal, when } from "@/lib/format";
import { useCancelSuiteRun, useSuite, useSuiteRun } from "@/lib/queries";
import {
  FINAL_RESULTS,
  type GateNumbers,
  type SuiteRun,
  type SuiteRunPart,
  WAITING_REASON_TEXT,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { RunSuiteDialog } from "@/pages/suite";

const FULL_COVERAGE = 0.95;

const COLUMNS = {
  open: "md:grid-cols-[8rem_minmax(0,1fr)_6rem_8rem_10rem]",
  final: "md:grid-cols-[8rem_minmax(0,1fr)_6rem_8rem_5rem_5rem_6rem]",
};

/** One start of a suite: its runs in entry order, each with its result against the suite run's
 * pass rate. While a run is at work, the page shows each run's progress. */
export function SuiteRunPage() {
  const { id = "" } = useParams();
  const suiteRun = useSuiteRun(id);
  if (suiteRun.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the suite run</AlertTitle>
        <AlertDescription>{suiteRun.error.message}</AlertDescription>
      </Alert>
    );
  }
  if (suiteRun.isPending) {
    return (
      <div className="grid gap-6">
        <Skeleton className="h-40 w-full rounded-lg" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
    );
  }
  return (
    <div className="grid gap-6">
      <Overview suiteRun={suiteRun.data} />
      <Runs suiteRun={suiteRun.data} />
    </div>
  );
}

function Overview({ suiteRun }: { suiteRun: SuiteRun }) {
  const final = FINAL_RESULTS.includes(suiteRun.result);
  const total = suiteRun.runs.reduce((sum, part) => sum + runTotal(part.run), 0);
  const finished = suiteRun.runs.reduce((sum, part) => sum + runFinished(part.run), 0);
  const sums = suiteRun.runs.reduce(
    (sum, { numbers }) => ({
      passed: sum.passed + numbers.passed + numbers.unplayed_passed,
      failed: sum.failed + numbers.failed + numbers.unplayed_failed,
      notScored: sum.notScored + numbers.not_scored + numbers.unplayed_not_scored,
    }),
    { passed: 0, failed: 0, notScored: 0 },
  );
  const failed = suiteRun.runs.filter((part) => part.result === "failed").length;
  const undecided = suiteRun.runs.filter((part) => part.result === "not_decided").length;
  const cancelled = suiteRun.runs.filter((part) => part.result === "cancelled").length;
  return (
    <Panel>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4 px-5 pt-5 pb-4">
        <div className="grid min-w-0 flex-1 basis-72 gap-1">
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="truncate text-h3-500">
              {suiteRun.suite_name}, {when(suiteRun.created_at)}
            </h1>
            <ResultLabel result={suiteRun.result} />
          </div>
          <p className="text-s-400 text-muted-foreground">
            Required pass rate {suiteRun.required_pass_percent}%, started{" "}
            {when(suiteRun.created_at)}
            {suiteRun.ended_at && `, ended ${when(suiteRun.ended_at)}`}
          </p>
        </div>
        <Actions suiteRun={suiteRun} />
      </div>
      <div className="grid gap-3 border-t px-5 py-4">
        {final ? (
          <>
            <span className="text-p-400 font-medium">
              {suiteRun.passed_run_count} of {counted(suiteRun.run_count, "run", "runs")} passed.
              {failed > 0 && ` ${failed} failed.`}
              {undecided > 0 && ` ${undecided} ${undecided === 1 ? "is" : "are"} not decided.`}
              {cancelled > 0 && ` ${cancelled} ${cancelled === 1 ? "was" : "were"} cancelled.`}
            </span>
            <div className="flex flex-wrap items-center gap-1.5 text-xs-400">
              <span className="mr-1 text-muted-foreground">
                {counted(suiteRun.conversation_count, "conversation", "conversations")}
              </span>
              <Badge variant="tag">Passed · {sums.passed}</Badge>
              <Badge variant="tag">Failed · {sums.failed}</Badge>
              <Badge variant="tag">Not scored · {sums.notScored}</Badge>
            </div>
          </>
        ) : (
          <>
            <span className="text-p-400 font-medium tabular-nums">
              {finished} of {counted(total, "conversation", "conversations")} finished
            </span>
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
                style={{ width: `${total ? (finished / total) * 100 : 0}%` }}
              />
            </div>
            <span className="text-s-400 text-muted-foreground">
              The result shows when every run has ended and the judges are done.
            </span>
          </>
        )}
      </div>
    </Panel>
  );
}

function Actions({ suiteRun }: { suiteRun: SuiteRun }) {
  const cancel = useCancelSuiteRun(suiteRun.id);
  const suite = useSuite(suiteRun.suite_id);
  const [cancelling, setCancelling] = useState(false);
  const [starting, setStarting] = useState(false);
  const running = suiteRun.result === "running" && !suiteRun.cancelled_at;
  return (
    <div className="flex gap-2">
      {running && (
        <Button variant="outline" size="sm" onClick={() => setCancelling(true)}>
          <Square />
          Cancel suite run
        </Button>
      )}
      {FINAL_RESULTS.includes(suiteRun.result) && suite.data && (
        <Button variant="outline" size="sm" onClick={() => setStarting(true)}>
          <Play />
          Run suite again
        </Button>
      )}
      <ConfirmDialog
        title="Cancel this suite run?"
        description="Every run of it is cancelled. Calls that have not started are cancelled, and calls on the line end. What was said so far is kept."
        action="Cancel suite run"
        cancel="Keep running"
        destructive
        pending={cancel.isPending}
        open={cancelling}
        onOpenChange={setCancelling}
        onConfirm={(close) =>
          cancel.mutate(undefined, {
            onSettled: close,
            onError: (error) =>
              toast.error("Could not cancel the suite run", { description: error.message }),
          })
        }
      />
      {starting && suite.data && (
        <RunSuiteDialog suite={suite.data} onClosed={() => setStarting(false)} />
      )}
    </div>
  );
}

/** The pass rate, or the range when calls are not scored; "Not yet" until the run's result. */
function rateText(part: SuiteRunPart): string {
  const { numbers } = part;
  if (!FINAL_RESULTS.includes(part.result)) return "Not yet";
  if (numbers.passed + numbers.failed + numbers.not_scored === 0) return "No caller talked";
  if (numbers.coverage !== null && numbers.coverage >= FULL_COVERAGE && numbers.pass_rate !== null)
    return percent(numbers.pass_rate);
  if (numbers.worst !== null && numbers.best !== null)
    return `${percent(numbers.worst)} to ${percent(numbers.best)}`;
  return "None";
}

function unplayed(numbers: GateNumbers): number {
  return numbers.unplayed_passed + numbers.unplayed_failed + numbers.unplayed_not_scored;
}

function Runs({ suiteRun }: { suiteRun: SuiteRun }) {
  const final = FINAL_RESULTS.includes(suiteRun.result);
  const grid = cn(
    "grid grid-cols-1 items-center gap-x-4 gap-y-1 px-5",
    final ? COLUMNS.final : COLUMNS.open,
  );
  const ranged = suiteRun.runs.some((part) => rateText(part).includes(" to "));
  const machines = suiteRun.runs.some((part) => unplayed(part.numbers) > 0);
  return (
    <Panel className="overflow-hidden">
      <PanelHeader title="Runs" />
      <div className={cn(grid, "hidden border-b py-3 text-label text-secondary md:grid")}>
        <span>Result</span>
        <span>Agent</span>
        <span>Connection</span>
        <span>Pass rate</span>
        {final ? (
          <>
            <span>Passed</span>
            <span>Failed</span>
            <span>Not scored</span>
          </>
        ) : (
          <span>Conversations</span>
        )}
      </div>
      <ul className="divide-y">
        {suiteRun.runs.map((part) => (
          <RunRow key={part.run.id} part={part} grid={grid} final={final} />
        ))}
      </ul>
      {final && (ranged || machines) && (
        <div className="grid gap-1 border-t bg-muted/40 px-5 py-3 text-xs-400 text-muted-foreground">
          {ranged && (
            <p>
              A range shows the pass rate if all not-scored conversations failed, and if they all
              passed. Not decided means they can change the result.
            </p>
          )}
          {machines && (
            <p>
              The pass rate counts the conversations where the caller talked. When no caller talked,
              the agent rules decide, and each of these conversations must pass.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}

function RunRow({ part, grid, final }: { part: SuiteRunPart; grid: string; final: boolean }) {
  const { run, numbers } = part;
  const machines = unplayed(numbers);
  const notPassed = numbers.unplayed_failed + numbers.unplayed_not_scored;
  return (
    <li
      className={cn(
        grid,
        "relative py-3.5 text-s-400 transition-colors duration-150 hover:bg-hv1 has-[a:focus-visible]:bg-hv1 has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring/50 has-[a:focus-visible]:ring-inset",
      )}
    >
      {part.result === "running" ? (
        <RunStatusLabel status={run.status} />
      ) : (
        <ResultLabel result={part.result} />
      )}
      <span className="grid min-w-0">
        <Link
          to={`/runs/${run.id}`}
          className="truncate text-s-500 outline-none after:absolute after:inset-0"
        >
          {run.agent_name}
        </Link>
        <span className="text-muted-foreground">Version {run.agent_version}</span>
      </span>
      <span>{run.transport === "phone" ? "Phone" : "Text"}</span>
      <span className="tabular-nums">{rateText(part)}</span>
      {final ? (
        <>
          <span className="tabular-nums">{numbers.passed}</span>
          <span className="tabular-nums">{numbers.failed}</span>
          <span className="tabular-nums">{numbers.not_scored}</span>
        </>
      ) : (
        <span className="grid tabular-nums">
          <span>
            {runFinished(run)} of {runTotal(run)} finished
          </span>
          {run.waiting_reason && (
            <span className="text-muted-foreground">{WAITING_REASON_TEXT[run.waiting_reason]}</span>
          )}
        </span>
      )}
      {final && machines > 0 && (
        <p className="col-span-full rounded-sm border bg-muted/40 px-3 py-2 text-xs-400 text-muted-foreground md:col-start-2">
          <span className="font-medium text-foreground">No caller talked:</span>{" "}
          {counted(machines, "call", "calls")}. {numbers.unplayed_passed} passed by the agent rules.
          {notPassed > 0 && (
            <>
              {" "}
              <span className="font-medium text-destructive">{notPassed} did not pass</span>
              {part.result === "failed" ? ", so the run failed." : "."}
            </>
          )}
        </p>
      )}
    </li>
  );
}
