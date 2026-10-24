import { CircleAlert, CircleCheck, CircleMinus, CircleX, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { CopyId } from "@/components/copy-id";
import { Spinner } from "@/components/ui/spinner";
import { ToolCalls } from "@/components/tool-calls";
import type { OnTurn } from "@/components/call-results";
import { clock, when } from "@/lib/format";
import { checkedValues, type HeardValueResult, type SavedValueResult } from "@/lib/record-checks";
import { useAgentRecord, useConversationEvaluation } from "@/lib/queries";
import type {
  AgentRecord,
  AgentRecordStatus,
  EvaluationState,
  RecordTool,
  RecordTurn,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export function AgentRecordPanel({
  conversationId,
  status,
  evaluation,
  connectedMs,
  onTurn,
}: {
  conversationId: string;
  status: AgentRecordStatus;
  evaluation: EvaluationState | null;
  connectedMs: number | undefined;
  onTurn?: OnTurn;
}) {
  const found = useAgentRecord(conversationId, status.status);
  const results = useConversationEvaluation(conversationId, evaluation);
  if (status.status === "waiting") {
    return (
      <Note>
        <Spinner className="size-3.5" />
        Waiting for the agent's record. The results come after it.
      </Note>
    );
  }
  if (found.isPending) return <Spinner />;
  if (found.isError) {
    return <Note danger>Could not load the agent record: {found.error.message}</Note>;
  }
  const record = found.data;
  if (record.status === "missing") {
    return (
      <div className="grid gap-4">
        <section
          aria-label="Record"
          className="grid gap-2 rounded-lg border bg-muted/30 px-4 py-3.5"
        >
          <span className="flex items-center gap-2 text-s-500">
            <CircleAlert className="size-4 text-status-warning" aria-hidden />
            No agent record
          </span>
          {record.reason && <p className="text-s-400">{sentence(record.reason)}</p>}
        </section>
        <Note>The saved data and heard checks did not run.</Note>
      </div>
    );
  }
  const items = results.data?.items ?? [];
  const saved = checkedValues<SavedValueResult>(
    items.find((item) => item.item_key === "saved_data"),
  );
  const heard = checkedValues<HeardValueResult>(items.find((item) => item.item_key === "heard"));
  return (
    <div className="grid gap-5">
      <Found record={record} />
      <SavedData record={record} results={saved} onTurn={onTurn} />
      <AgentTranscript
        record={record}
        heard={heard}
        connectedMs={connectedMs ?? 0}
        onTurn={onTurn}
      />
    </div>
  );
}

function sentence(text: string): string {
  const first = text.charAt(0).toUpperCase() + text.slice(1);
  return first.endsWith(".") ? first : `${first}.`;
}

function Found({ record }: { record: AgentRecord }) {
  return (
    <section aria-label="Record" className="grid gap-2.5 rounded-lg border bg-muted/30 px-4 py-3.5">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-s-500">
          {record.reason ? (
            <TriangleAlert className="size-4 text-status-warning" aria-hidden />
          ) : (
            <CircleCheck className="size-4 text-status-success" aria-hidden />
          )}
          Found in {record.provider_label}
          {record.reason && ", may be incomplete"}
        </span>
        {record.external_id && <CopyId id={record.external_id} label="record ID" />}
      </div>
      {record.reason && <p className="text-xs-400 text-foreground">{sentence(record.reason)}</p>}
      <dl className="grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs-400">
        <dt className="text-muted-foreground">Record ID</dt>
        <dd className="font-mono break-all">{record.external_id}</dd>
        {record.provider_status && (
          <>
            <dt className="text-muted-foreground">Status</dt>
            <dd>{record.provider_status}</dd>
          </>
        )}
        {record.fetched_at && (
          <>
            <dt className="text-muted-foreground">Read</dt>
            <dd>{when(record.fetched_at)}</dd>
          </>
        )}
      </dl>
    </section>
  );
}

const SAVED_RESULT = {
  matches: { text: "Matches", icon: CircleCheck, tone: "text-status-success" },
  contradicts: { text: "Does not match", icon: CircleX, tone: "text-status-danger" },
  not_checkable: { text: "Not checkable", icon: CircleMinus, tone: "text-muted-foreground" },
} as const;

function SavedData({
  record,
  results,
  onTurn,
}: {
  record: AgentRecord;
  results: SavedValueResult[] | null;
  onTurn?: OnTurn;
}) {
  const byName = new Map((results ?? []).map((result) => [result.name, result]));
  return (
    <section aria-label="Saved data" className="grid gap-2">
      <h3 className="text-label text-muted-foreground">
        Saved data <span className="tabular-nums">{record.saved.length}</span>
      </h3>
      {record.saved.length === 0 ? (
        <Note>The agent saved no values.</Note>
      ) : (
        <ul className="grid grid-cols-[fit-content(50%)_minmax(0,1fr)_auto] divide-y overflow-hidden rounded-lg border">
          {record.saved.map((value) => {
            const result = byName.get(value.name);
            const shown = result ? SAVED_RESULT[result.result] : null;
            return (
              <li
                key={value.name}
                className="col-span-full grid grid-cols-subgrid gap-x-3 gap-y-1.5 px-3 py-2.5"
              >
                <span className="col-span-full grid grid-cols-subgrid items-start">
                  <span className="font-mono text-xs-500 break-all">{value.name}</span>
                  <span
                    className={cn(
                      "text-s-400 break-words",
                      value.value === "" && "text-muted-foreground",
                    )}
                  >
                    {value.value || "(empty)"}
                  </span>
                  {shown && (
                    <span className={cn("flex items-center gap-1 text-xs-500", shown.tone)}>
                      <shown.icon className="size-3.5" aria-hidden />
                      {shown.text}
                    </span>
                  )}
                </span>
                {result?.result === "contradicts" && (
                  <span className="col-span-full grid gap-1">
                    {result.evidence.map((quote) => (
                      <span key={`${quote.turn}-${quote.quote}`} className="flex gap-2 text-xs-400">
                        <TurnChip turn={quote.turn} onTurn={onTurn} />
                        <q className="min-w-0 break-words">{quote.quote}</q>
                      </span>
                    ))}
                    <span className="text-xs-400 text-muted-foreground">{result.reasoning}</span>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

type Line =
  | { kind: "turn"; turn: RecordTurn; heard: number | null }
  | { kind: "tool"; tool: RecordTool };

/** The record's lines and tool calls in one list, each tool call before the first line that
 * comes after it. */
function timeline(record: AgentRecord): Line[] {
  const tools = [...record.tools];
  const lines: Line[] = [];
  let heard = 0;
  for (const turn of record.turns) {
    while (tools.length && turn.at_ms !== null && (tools[0].at_ms ?? Infinity) <= turn.at_ms) {
      lines.push({ kind: "tool", tool: tools.shift() as RecordTool });
    }
    lines.push({ kind: "turn", turn, heard: turn.role === "caller" ? ++heard : null });
  }
  return [...lines, ...tools.map((tool) => ({ kind: "tool" as const, tool }))];
}

function AgentTranscript({
  record,
  heard,
  connectedMs,
  onTurn,
}: {
  record: AgentRecord;
  heard: HeardValueResult[] | null;
  connectedMs: number;
  onTurn?: OnTurn;
}) {
  const lines = timeline(record);
  const missing = (heard ?? []).filter((value) => value.result === "missing");
  return (
    <section aria-label="The agent's transcript" className="grid gap-2">
      <h3 className="text-label text-muted-foreground">
        The agent's transcript <span className="tabular-nums">{lines.length}</span>
      </h3>
      <p className="text-xs-400 text-muted-foreground">
        As the agent recorded it: its own words, what its speech-to-text heard, and its tool calls.
      </p>
      {lines.length === 0 ? (
        <Note>The record has no lines.</Note>
      ) : (
        <ol className="divide-y overflow-hidden rounded-lg border">
          {lines.map((line, index) =>
            line.kind === "tool" ? (
              <li key={`tool-${index}`} className="grid gap-1.5 py-2.5 pr-3 pl-12">
                <span className="text-xs-400 text-muted-foreground">
                  Tool call
                  {line.tool.at_ms !== null && ` · ${clock(line.tool.at_ms - connectedMs)}`}
                  {line.tool.failed && " · failed"}
                </span>
                <ToolCalls
                  tools={[
                    {
                      id: String(index),
                      name: line.tool.name,
                      arguments: line.tool.arguments,
                      output: line.tool.output,
                    },
                  ]}
                />
              </li>
            ) : (
              <RecordLine
                key={`turn-${index}`}
                turn={line.turn}
                marks={(heard ?? []).filter((value) => value.heard?.line === line.heard)}
                connectedMs={connectedMs}
                onTurn={onTurn}
              />
            ),
          )}
        </ol>
      )}
      {missing.length > 0 && (
        <ul className="grid gap-1">
          {missing.map((value) => (
            <li
              key={value.value}
              className="flex items-center gap-1.5 text-xs-500 text-status-danger"
            >
              <CircleX className="size-3.5" aria-hidden />
              {value.value} not heard: the caller said "{value.said.quote}"
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecordLine({
  turn,
  marks,
  connectedMs,
  onTurn,
}: {
  turn: RecordTurn;
  marks: HeardValueResult[];
  connectedMs: number;
  onTurn?: OnTurn;
}) {
  const wrong = marks.find((mark) => mark.result === "different")?.heard?.quote ?? null;
  return (
    <li className="flex gap-2.5 px-3 py-2.5">
      <span className="w-9 shrink-0">
        {turn.turn !== null && <TurnChip turn={turn.turn} onTurn={onTurn} />}
      </span>
      <span className="grid min-w-0 gap-1">
        <span
          className={cn(
            "text-xs-500",
            turn.role === "agent" ? "text-primary" : "text-muted-foreground",
          )}
        >
          {turn.role === "agent" ? "Agent" : "Caller, as heard"}
          {turn.at_ms !== null && ` · ${clock(turn.at_ms - connectedMs)}`}
        </span>
        <span className="text-s-400 break-words">{highlighted(turn.text, wrong)}</span>
        {marks.map((mark) =>
          mark.result === "same" ? (
            <span
              key={mark.value}
              className="flex items-center gap-1 text-xs-500 text-status-success"
            >
              <CircleCheck className="size-3.5" aria-hidden />
              {mark.value} heard as said
            </span>
          ) : (
            <span
              key={mark.value}
              className="flex items-center gap-1 text-xs-500 text-status-danger"
            >
              <CircleX className="size-3.5" aria-hidden />
              {mark.value} misheard: the caller said "{mark.said.quote}"
            </span>
          ),
        )}
      </span>
    </li>
  );
}

function highlighted(text: string, wrong: string | null): ReactNode {
  const at = wrong ? text.toLowerCase().indexOf(wrong.toLowerCase()) : -1;
  if (wrong === null || at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-sm bg-status-danger/15 px-0.5 font-semibold text-foreground">
        {text.slice(at, at + wrong.length)}
      </mark>
      {text.slice(at + wrong.length)}
    </>
  );
}

function TurnChip({ turn, onTurn }: { turn: number; onTurn?: OnTurn }) {
  const chip =
    "shrink-0 rounded-sm bg-muted px-1.5 font-mono text-xs-400 text-muted-foreground tabular-nums";
  if (!onTurn) return <span className={chip}>T{turn}</span>;
  return (
    <button
      type="button"
      title={`Show turn ${turn} in the transcript`}
      aria-label={`Show turn ${turn} in the transcript`}
      onClick={() => onTurn(turn)}
      className={cn(
        chip,
        "outline-none transition-colors duration-150 hover:bg-foreground hover:text-background focus-visible:ring-2 focus-visible:ring-ring/50",
      )}
    >
      T{turn}
    </button>
  );
}

function Note({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
  return (
    <p
      role={danger ? "alert" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-lg border border-dashed px-4 py-3 text-s-400",
        danger ? "text-status-danger" : "text-muted-foreground",
      )}
    >
      {children}
    </p>
  );
}
