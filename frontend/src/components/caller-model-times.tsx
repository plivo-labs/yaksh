import { Panel, PanelHeader } from "@/components/panel";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { latency } from "@/lib/format";
import { useCallerReplyTimes } from "@/lib/queries";

/** How long the caller took to reply with each model and effort in the recent phone calls, to
 * help choose the caller's model. */
export function CallerModelTimes() {
  const times = useCallerReplyTimes();
  const days = times.data?.days;
  return (
    <Panel className="overflow-hidden">
      <PanelHeader title="Caller reply time by model" />
      {days !== undefined && (
        <p className="px-5 pt-3 text-s-400 text-muted-foreground">
          Phone calls of the last {days} days, scenarios with their own model included.
        </p>
      )}
      {times.isError ? (
        <p role="alert" className="px-5 py-4 text-s-400 text-status-danger">
          Could not load the reply times: {times.error.message}
        </p>
      ) : times.data && times.data.rows.length === 0 ? (
        <p className="px-5 py-4 text-s-400 text-muted-foreground">
          No measured caller replies in the last {days} days.
        </p>
      ) : (
        <Table className="mt-3 border-t">
          <TableHeader>
            <TableRow>
              <TableHead className="pl-5">Model</TableHead>
              <TableHead>Effort</TableHead>
              <TableHead className="text-right">Calls</TableHead>
              <TableHead className="text-right">Reply p50</TableHead>
              <TableHead className="text-right">Reply p90</TableHead>
              <TableHead className="pr-5 text-right">LLM p50</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {times.data?.rows.map((row) => (
              <TableRow key={`${row.model} ${row.reasoning_effort}`}>
                <TableCell className="pl-5">
                  <span className="flex items-center gap-2">
                    {row.model}
                    {row.in_use && <Badge variant="tag">In use</Badge>}
                  </span>
                </TableCell>
                <TableCell>{row.reasoning_effort ?? "None"}</TableCell>
                <TableCell className="text-right tabular-nums">{row.calls}</TableCell>
                <TableCell className="text-right text-s-500 tabular-nums">
                  {latency(row.p50_ms)}
                </TableCell>
                <TableCell className="text-right tabular-nums">{latency(row.p90_ms)}</TableCell>
                <TableCell className="pr-5 text-right tabular-nums">
                  {latency(row.llm_p50_ms)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
