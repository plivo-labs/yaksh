import { Fact, Panel, PanelHeader } from "@/components/panel";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { noiseLabel, percent, seconds, shareText } from "@/lib/format";
import { useRunMetrics } from "@/lib/queries";
import { CATEGORY_LABELS, FLAG_TEXT, type RunNumbers, type Share } from "@/lib/types";

/** The run's numbers over its counted calls, overall and by group. */
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
      <PanelHeader title="Metrics" />
      <p className="border-b px-5 py-2.5 text-xs text-muted-foreground">
        Over the latest attempt of each repeat, without cancelled calls. Each share counts calls.
        The shares above the table show their 95% interval: with few calls, the interval is wide.
      </p>
      <dl className="grid grid-cols-1 gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-4">
        <Fact wrap label="Evaluated">
          {overall.evaluated} of {overall.conversations}
          {overall.pending > 0 && `, ${overall.pending} pending`}
          {overall.failed > 0 && `, ${overall.failed} failed`}
        </Fact>
        <Fact wrap label="Connected">
          {shareText(overall.connected)}
          {overall.errors_before_connect > 0 &&
            `; Truman errors before connecting: ${overall.errors_before_connect}`}
        </Fact>
        <Fact wrap label="Response p50 / p90">
          {overall.response_p50_ms === null || overall.response_p90_ms === null
            ? "None yet"
            : `${seconds(overall.response_p50_ms)} / ${seconds(overall.response_p90_ms)}`}
        </Fact>
        <Fact wrap label="Calls with an unanswered reply">
          {shareText(overall.unanswered)}
        </Fact>
        <Fact wrap label="Calls where the agent spoke over the caller">
          {shareText(overall.talked_over)}
        </Fact>
        <Fact wrap label="Calls with a wait of 5s or more">
          {shareText(overall.long_wait)}
        </Fact>
        <Fact wrap label="Calls with a silence of 10s or more">
          {shareText(overall.dead_air)}
        </Fact>
        <Fact wrap label="Flags raised">
          {flags.length === 0
            ? "None"
            : flags
                .map(
                  ([flag, calls]) =>
                    `${FLAG_TEXT[flag] ?? flag}: ${calls} ${calls === 1 ? "call" : "calls"}`,
                )
                .join("; ")}
        </Fact>
      </dl>
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
          <TableHead>5s wait</TableHead>
          <TableHead className="pr-5">10s silence</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(([label, numbers]) => (
          <TableRow key={label}>
            <TableCell className="pl-5">{label}</TableCell>
            <TableCell className="tabular-nums">{numbers.conversations}</TableCell>
            <TableCell className="tabular-nums">{cell(numbers.connected)}</TableCell>
            <TableCell className="tabular-nums">
              {numbers.response_p90_ms === null ? "None yet" : seconds(numbers.response_p90_ms)}
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

function cell(share: Share): string {
  return share.total === 0
    ? "None yet"
    : `${percent(share.count / share.total)} (${share.count}/${share.total})`;
}
