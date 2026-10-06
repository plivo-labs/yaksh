import { Panel, PanelHeader } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Explained, Meter, Stat } from "@/components/verdict-ui";
import { BAND_TEXT, counted, noiseLabel, percent, responseBand, seconds } from "@/lib/format";
import { useRunMetrics } from "@/lib/queries";
import { CATEGORY_LABELS, FLAG_TEXT, type RunNumbers, type Share } from "@/lib/types";
import { cn } from "@/lib/utils";

const PROBLEMS: {
  key: "unanswered" | "talked_over" | "long_wait" | "dead_air";
  label: string;
  hint: string;
}[] = [
  {
    key: "unanswered",
    label: "A reply was not answered",
    hint: "Calls where the caller said something that expected an answer, and the agent never answered it.",
  },
  {
    key: "talked_over",
    label: "The agent spoke over the caller",
    hint: "Calls where the agent started to speak before the caller finished.",
  },
  {
    key: "long_wait",
    label: "A wait of 5 s or more",
    hint: "Calls where the caller waited 5 s or more for the agent's answer.",
  },
  {
    key: "dead_air",
    label: "A silence of 10 s or more",
    hint: "Calls with 10 s or more of silence.",
  },
];

/** The run's numbers over its counted calls: how fast the agent answered, which problems the
 * calls had and how often, and the same by group. */
export function RunMetricsPanel({ runId, active }: { runId: string; active: boolean }) {
  const metrics = useRunMetrics(runId, active);
  if (metrics.isPending) return <Skeleton className="h-48 w-full rounded-lg" />;
  if (metrics.isError) {
    return (
      <p role="alert" className="text-s-400 text-status-danger">
        Could not load the run metrics: {metrics.error.message}
      </p>
    );
  }
  const { overall, by_category, by_noise } = metrics.data;
  const flags = Object.entries(overall.flags);
  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title="Call metrics"
        action={
          <span className="text-xs-400 text-muted-foreground">
            The latest attempt of each repeat, without cancelled calls
          </span>
        }
      />
      <div className="grid grid-cols-1 gap-3 border-b bg-muted/30 px-5 py-4 sm:grid-cols-3">
        <Stat
          label="Response time"
          hint="How long the agent took to start its answer after the caller finished, over every reply of the run: half the replies were faster than the first number, nine in ten faster than the second."
          value={
            overall.response_p50_ms === null ? (
              "None yet"
            ) : (
              <span className={BAND_TEXT[responseBand(overall.response_p50_ms)]}>
                {seconds(overall.response_p50_ms)}
              </span>
            )
          }
        >
          <p className="text-xs-400 text-muted-foreground">
            {overall.response_p90_ms === null ? (
              "Measured once calls are evaluated."
            ) : (
              <>
                Half the replies were faster. Nine in ten were faster than{" "}
                <span
                  className={cn("font-medium", BAND_TEXT[responseBand(overall.response_p90_ms)])}
                >
                  {seconds(overall.response_p90_ms)}
                </span>
                .
              </>
            )}
          </p>
        </Stat>
        <Stat
          label="Connected"
          hint="Calls where Yaksha and the agent were on the line together."
          value={
            <>
              {overall.connected.count}
              <span className="text-s-400 text-muted-foreground">
                {" "}
                of {overall.connected.total}
              </span>
            </>
          }
        >
          <Meter
            value={overall.connected.total ? overall.connected.count / overall.connected.total : 0}
            tone={overall.connected.count === overall.connected.total ? "good" : "warn"}
            label="Connected"
          />
          <p className="text-xs-400 text-muted-foreground">
            {overall.errors_before_connect > 0
              ? `${counted(overall.errors_before_connect, "Yaksha error", "Yaksha errors")} before connecting.`
              : "No Yaksha error before connecting."}
          </p>
        </Stat>
        <Stat
          label="Evaluated"
          hint="Calls whose metrics and verdicts are done."
          value={
            <>
              {overall.evaluated}
              <span className="text-s-400 text-muted-foreground"> of {overall.conversations}</span>
            </>
          }
        >
          <Meter
            value={overall.conversations ? overall.evaluated / overall.conversations : 0}
            tone="neutral"
            label="Evaluated"
          />
          <p className="text-xs-400 text-muted-foreground">
            {[
              overall.pending > 0 && `${overall.pending} still being evaluated`,
              overall.failed > 0 && `${overall.failed} failed`,
            ]
              .filter(Boolean)
              .join(" · ") || "All done."}
          </p>
        </Stat>
      </div>
      <section aria-label="Problems in the calls" className="grid gap-1 px-5 py-4">
        <h3 className="mb-1 text-s-500">Problems in the calls</h3>
        {PROBLEMS.map((problem) => (
          <ProblemRow
            key={problem.key}
            label={problem.label}
            hint={problem.hint}
            share={overall[problem.key]}
          />
        ))}
        {flags.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs-400 text-muted-foreground">Flags</span>
            {flags.map(([flag, calls]) => (
              <Badge key={flag} variant="tag">
                {FLAG_TEXT[flag] ?? flag} · {calls}
              </Badge>
            ))}
          </div>
        )}
      </section>
      <Breakdown
        title="Scenario category"
        rows={by_category.map((group) => [CATEGORY_LABELS[group.category], group.numbers])}
      />
      <Breakdown
        title="Background noise"
        rows={by_noise.map((group) => [noiseLabel(group.noise) ?? "None", group.numbers])}
      />
    </Panel>
  );
}

function intervalText(share: Share): string {
  if (share.low === null || share.high === null) return "";
  return ` With this many calls, the true share is likely between ${percent(share.low)} and ${percent(share.high)}.`;
}

function ProblemRow({ label, hint, share }: { label: string; hint: string; share: Share }) {
  const rate = share.total ? share.count / share.total : 0;
  return (
    <div className="grid grid-cols-[minmax(0,14rem)_minmax(0,1fr)_7rem] items-center gap-x-4 py-1">
      <Explained hint={`${hint}${intervalText(share)}`} className="justify-self-start text-s-400">
        {label}
      </Explained>
      <Meter
        value={rate}
        tone={share.count === 0 ? "good" : rate >= 0.2 ? "bad" : "warn"}
        label={label}
      />
      <span className="text-right text-xs-400 tabular-nums">
        {share.total === 0 ? (
          <span className="text-muted-foreground">None yet</span>
        ) : (
          <>
            <span className="font-medium">{share.count}</span>
            <span className="text-muted-foreground">
              {" "}
              of {share.total} · {percent(rate)}
            </span>
          </>
        )}
      </span>
    </div>
  );
}

/** One row for each group; nothing when all the calls are in one group. */
function Breakdown({ title, rows }: { title: string; rows: [string, RunNumbers][] }) {
  if (rows.length < 2) return null;
  return (
    <Table className="border-t">
      <TableHeader>
        <TableRow>
          <TableHead className="pl-5">{title}</TableHead>
          <TableHead>Calls</TableHead>
          <TableHead>Connected</TableHead>
          <TableHead>Response p90</TableHead>
          <TableHead>Unanswered</TableHead>
          <TableHead>5 s wait</TableHead>
          <TableHead className="pr-5">10 s silence</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(([label, numbers]) => (
          <TableRow key={label}>
            <TableCell className="pl-5">{label}</TableCell>
            <TableCell className="tabular-nums">{numbers.conversations}</TableCell>
            <TableCell className="tabular-nums">{cell(numbers.connected)}</TableCell>
            <TableCell className="tabular-nums">
              {numbers.response_p90_ms === null ? (
                <span className="text-muted-foreground">None yet</span>
              ) : (
                <span className={BAND_TEXT[responseBand(numbers.response_p90_ms)]}>
                  {seconds(numbers.response_p90_ms)}
                </span>
              )}
            </TableCell>
            <TableCell className="tabular-nums">{cell(numbers.unanswered)}</TableCell>
            <TableCell className="tabular-nums">{cell(numbers.long_wait)}</TableCell>
            <TableCell className="pr-5 tabular-nums">{cell(numbers.dead_air)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function cell(share: Share) {
  if (share.total === 0) return <span className="text-muted-foreground">None yet</span>;
  return (
    <>
      {percent(share.count / share.total)}
      <span className="text-muted-foreground">
        {" "}
        ({share.count}/{share.total})
      </span>
    </>
  );
}
