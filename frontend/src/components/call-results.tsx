import { ChevronRight } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";

import { Spinner } from "@/components/ui/spinner";
import { Explained, OutcomeIcon, VerdictPill } from "@/components/verdict-ui";
import { percent } from "@/lib/format";
import { useConversationEvaluation } from "@/lib/queries";
import {
  checkedValues,
  passedChecks,
  type HeardValueResult,
  type SavedValueResult,
} from "@/lib/record-checks";
import {
  DECIDED_BY_TEXT,
  ERROR_TEXT,
  type EvaluationItem,
  type EvaluationState,
  OUTCOME_TEXT,
  type Outcome,
  UNSURE_TEXT,
  VERDICT_TEXT,
  type Verdict,
  evaluationPending,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/** Shows the call from the start of that turn, counted from 1. */
export type OnTurn = (turn: number) => void;

const GROUPS: { title: string; matches: (key: string) => boolean }[] = [
  { title: "Criteria", matches: (key) => key.startsWith("criterion-") },
  { title: "Agent rules", matches: (key) => key.startsWith("rule-") },
  { title: "Agent record", matches: (key) => key === "saved_data" || key === "heard" },
  {
    title: "Reports",
    matches: (key) => key === "instructions" || key === "hallucination" || key === "caller_check",
  },
];

/** Outcomes that need a look: their rows start open. */
const PROBLEMS: ReadonlySet<Outcome> = new Set(["fail", "blocked", "error", "unsure", "pending"]);

/** What the judges found in the call. The verdicts and a count of outcomes come first; each
 * criterion, rule and report is one row, open when it needs a look, with its quotes, effects
 * and reasoning inside. */
export function CallResults({
  conversationId,
  evaluation,
  onTurn,
  notPlayed = null,
}: {
  conversationId: string;
  evaluation: EvaluationState | null;
  onTurn?: OnTurn;
  /** Why the scenario's criteria were not judged: no caller talked on the call. */
  notPlayed?: string | null;
}) {
  const found = useConversationEvaluation(conversationId, evaluation);
  if (evaluation === null) {
    return <Note>Results appear once the conversation has ended and been judged.</Note>;
  }
  if (evaluationPending(evaluation)) {
    return (
      <Note>
        <Spinner className="size-3.5" />
        Judging the conversation.
      </Note>
    );
  }
  if (found.isError) {
    return <Note danger>Could not load the results: {found.error.message}</Note>;
  }
  const data = found.data;
  if (!data) return null;
  if (evaluation === "failed") {
    return <Note danger>The evaluation failed{data.failure ? `: ${data.failure}` : "."}</Note>;
  }
  if (data.scenario_verdict === null && data.items.length === 0) {
    return (
      <Note>
        Not judged. The judges read completed conversations that no one stopped, when the server has
        a judge model.
      </Note>
    );
  }
  const counted = data.items.filter(
    (item) => item.item_key.startsWith("criterion-") || item.role === "deciding",
  );
  return (
    <div className="grid gap-5">
      {data.scenario_verdict !== null && (
        <section
          aria-label="Verdicts"
          className="grid gap-3 rounded-lg border bg-muted/30 px-4 py-3.5"
        >
          <dl className="grid grid-cols-2 gap-3">
            <VerdictFact
              kind="scenario"
              machine={data.scenario_verdict}
              effective={data.effective_scenario_verdict}
            />
            <VerdictFact
              kind="conversation"
              machine={data.conversation_verdict}
              effective={data.effective_conversation_verdict}
            />
          </dl>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2.5">
            <OutcomeCounts items={counted} />
            <Link
              to={`/review/${conversationId}?seen=1`}
              className="rounded-sm text-xs-500 text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              Label this conversation
            </Link>
          </div>
        </section>
      )}
      {notPlayed && data.scenario_verdict !== null && (
        <section aria-label="Criteria" className="grid gap-2">
          <h3 className="text-label text-muted-foreground">Criteria</h3>
          <Note>Not judged. {notPlayed}</Note>
        </section>
      )}
      {GROUPS.map(({ title, matches }) => {
        const items = data.items.filter((item) => matches(item.item_key));
        if (items.length === 0) return null;
        return (
          <section key={title} aria-label={title} className="grid gap-2">
            <h3 className="text-label text-muted-foreground">
              {title} <span className="tabular-nums">{items.length}</span>
            </h3>
            <ul className="divide-y overflow-hidden rounded-lg border">
              {items.map((item) => (
                <ItemRow key={item.item_key} item={item} onTurn={onTurn} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
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

const ORDER: Outcome[] = [
  "pass",
  "fail",
  "blocked",
  "unsure",
  "error",
  "pending",
  "not_applicable",
];

/** How the items a verdict counts came out, as icons and numbers. */
function OutcomeCounts({ items }: { items: EvaluationItem[] }) {
  const counts = new Map<Outcome, number>();
  for (const item of items) {
    counts.set(item.effective_outcome, (counts.get(item.effective_outcome) ?? 0) + 1);
  }
  return (
    <ul
      aria-label="Outcomes of the criteria and counted rules"
      className="flex flex-wrap gap-x-3 gap-y-1"
    >
      {ORDER.filter((outcome) => counts.get(outcome)).map((outcome) => (
        <li key={outcome} className="flex items-center gap-1 text-xs-500 tabular-nums">
          <OutcomeIcon outcome={outcome} className="size-3.5" decorative />
          {counts.get(outcome)}
          <span className="font-normal text-muted-foreground">
            {OUTCOME_TEXT[outcome].toLowerCase()}
          </span>
        </li>
      ))}
    </ul>
  );
}

const VERDICT_KINDS = {
  scenario: {
    label: "Scenario",
    hint: "From the scenario's criteria only.",
  },
  conversation: {
    label: "With agent rules",
    hint: "The scenario's criteria, the agent rules set to count in the conversation's verdict, and the check of the data the agent saved. Rules and checks that only report do not change it.",
  },
} as const;

export type VerdictKind = keyof typeof VERDICT_KINDS;

/** A verdict's name, with what it counts on hover or focus. */
export function VerdictLabel({ kind }: { kind: VerdictKind }) {
  return (
    <Explained hint={VERDICT_KINDS[kind].hint} className="text-xs-400 text-muted-foreground">
      {VERDICT_KINDS[kind].label}
    </Explained>
  );
}

function VerdictFact({
  kind,
  machine,
  effective,
}: {
  kind: VerdictKind;
  machine: Verdict | null;
  effective: Verdict | null;
}) {
  if (machine === null || effective === null) return null;
  return (
    <div className="grid content-start gap-1.5">
      <dt className="justify-self-start">
        <VerdictLabel kind={kind} />
      </dt>
      <dd className="grid justify-items-start gap-1">
        <VerdictPill verdict={effective} />
        {effective !== machine && (
          <span className="text-xs-400 text-muted-foreground">
            Labels changed it from {VERDICT_TEXT[machine].toLowerCase()}
          </span>
        )}
      </dd>
    </div>
  );
}

type Quote = { turn: number; quote: string };
type Part = {
  verdict: string;
  call_quote: Quote | null;
  instruction_quote: string | null;
  reasoning?: string;
};

const INSTRUCTION_PARTS = [
  ["objective", "Goal"],
  ["procedure", "Steps"],
  ["boundary", "Limits"],
] as const;

const BLAME_TEXT: Record<string, string> = {
  none: "Kept to its test",
  possible: "May have changed a result",
  likely: "Likely changed a result",
};

/** The one line under an item's name: its outcome, and what most explains it. */
function summary(item: EvaluationItem): string {
  const answer = item.answer ?? {};
  if (item.item_key === "instructions" && item.effective_outcome !== "error") {
    const parts = INSTRUCTION_PARTS.flatMap(([key, name]) => {
      const part = answer[key] as Part | undefined;
      if (!part || part.verdict === "not_applicable") return [];
      return [`${name} ${part.verdict === "pass" ? "kept" : "not kept"}`];
    });
    return parts.join(" · ") || "Nothing in the instructions applied";
  }
  if (item.item_key === "hallucination" && item.effective_outcome !== "error") {
    const found = (answer.contradictions as unknown[] | undefined)?.length ?? 0;
    return found === 0
      ? "Nothing the agent said contradicts the documents"
      : `${found} ${found === 1 ? "statement contradicts" : "statements contradict"} the documents`;
  }
  const saved = item.item_key === "saved_data" ? checkedValues<SavedValueResult>(item) : null;
  if (saved) {
    const count = (result: string) => saved.filter((value) => value.result === result).length;
    return [
      count("matches") && `${count("matches")} match`,
      count("contradicts") && `${count("contradicts")} do not match`,
      count("not_checkable") && `${count("not_checkable")} not checkable`,
    ]
      .filter(Boolean)
      .join(", ");
  }
  const heard = item.item_key === "heard" ? checkedValues<HeardValueResult>(item) : null;
  if (heard) {
    const wrong = heard.filter((value) => value.result !== "same").length;
    if (heard.length === 0) return "No values to compare · reports only";
    return wrong === 0
      ? "Every value heard as said · reports only"
      : `${wrong} of ${heard.length} values misheard · reports only`;
  }
  if (item.item_key === "caller_check" && typeof answer.blame_risk === "string") {
    return BLAME_TEXT[answer.blame_risk] ?? answer.blame_risk;
  }
  const outcome = OUTCOME_TEXT[item.effective_outcome];
  if (item.error_reason) return `${outcome}: ${ERROR_TEXT[item.error_reason] ?? item.error_reason}`;
  if (item.caller_effect) return `${outcome}: ${callerEffectShort(item.caller_effect)}`;
  if (item.effective_outcome === "unsure" && item.effective_unsure_kind) {
    return `${outcome}: ${UNSURE_TEXT[item.effective_unsure_kind]}`;
  }
  return `${outcome} · ${decidedBy(item)}`;
}

function callerEffectShort(found: NonNullable<EvaluationItem["caller_effect"]>): string {
  if (found.blame === null) return "the caller check failed on a conversation a test limit ended";
  if (found.owner === "test_settings") return "the test's turn or time limit cut it off";
  if (found.owner === "scenario") return "the scenario cannot pass as written";
  return found.blame === "likely"
    ? "Yaksh's caller likely changed it"
    : "Yaksh's caller may have changed it";
}

/** What the caller check found for a criterion, by who caused it. */
function callerEffect(found: NonNullable<EvaluationItem["caller_effect"]>): string {
  if (found.blame === null) {
    return "The caller check failed on a conversation that a test limit ended, so this is not scored.";
  }
  if (found.owner === "test_settings") {
    return `The test's turn or time limit cut this off: ${found.effect}`;
  }
  if (found.owner === "scenario") return `The scenario cannot pass as written: ${found.effect}`;
  const how = found.blame === "likely" ? "likely changed" : "may have changed";
  return `Yaksh's caller ${how} this: ${found.effect}`;
}

function decidedBy(item: EvaluationItem): string {
  const meets = item.jev_probabilities?.meets;
  if (item.decided_by === "jev" && meets !== undefined) return `Jev, ${percent(meets)} sure`;
  return DECIDED_BY_TEXT[item.decided_by];
}

function number(item: EvaluationItem): string | null {
  return item.item_key.startsWith("criterion-") ? item.item_key.slice("criterion-".length) : null;
}

function ItemRow({ item, onTurn }: { item: EvaluationItem; onTurn?: OnTurn }) {
  const [open, setOpen] = useState(PROBLEMS.has(item.effective_outcome));
  const id = `item-${item.item_key}`;
  const n = number(item);
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left outline-none transition-colors duration-150 hover:bg-hv1 focus-visible:bg-hv1 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
      >
        <OutcomeIcon outcome={item.effective_outcome} className="mt-0.5" />
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className={cn("text-s-400 wrap-anywhere", !open && "line-clamp-2")}>
            {n && <span className="mr-1.5 text-muted-foreground tabular-nums">{n}</span>}
            {item.subject}
          </span>
          <span className="text-xs-400 text-muted-foreground">{summary(item)}</span>
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform duration-150 ease-out motion-reduce:transition-none",
            open && "rotate-90",
          )}
        />
      </button>
      {open && (
        <div id={id} className="pr-3 pb-3 pl-9">
          <ItemDetails item={item} onTurn={onTurn} />
        </div>
      )}
    </li>
  );
}

/** One item with everything about it shown, for a labeler comparing with the machine. */
export function ItemResult({
  item,
  onTurn,
  machineOnly = false,
}: {
  item: EvaluationItem;
  onTurn?: OnTurn;
  /** Show what the machine decided, not the outcome after labels. */
  machineOnly?: boolean;
}) {
  const outcome = machineOnly ? item.machine_outcome : item.effective_outcome;
  return (
    <li className="grid gap-2">
      <div className="flex items-center gap-2">
        <OutcomeIcon outcome={outcome} decorative />
        <span className="text-s-500">{OUTCOME_TEXT[outcome]}</span>
        <span className="text-xs-400 text-muted-foreground">
          {machineOnly ? "The machine's answer" : item.subject} · {decidedBy(item)}
        </span>
      </div>
      <ItemDetails item={item} onTurn={onTurn} machineOnly={machineOnly} />
    </li>
  );
}

/** Everything about one item: what changed it, what the judge quoted and why it decided. */
function ItemDetails({
  item,
  onTurn,
  machineOnly = false,
}: {
  item: EvaluationItem;
  onTurn?: OnTurn;
  machineOnly?: boolean;
}) {
  const outcome = machineOnly ? item.machine_outcome : item.effective_outcome;
  const kind = machineOnly ? item.unsure_kind : item.effective_unsure_kind;
  const facts = [
    `Decided by ${decidedBy(item).toLowerCase().replace("jev", "Jev")}`,
    item.role === "deciding" &&
      !item.item_key.startsWith("criterion-") &&
      "counts in the conversation's verdict",
    item.item_key === "heard" && "reports only, does not change a verdict",
    outcome === "unsure" && kind && UNSURE_TEXT[kind],
    !machineOnly &&
      outcome !== item.machine_outcome &&
      `labels changed it from ${OUTCOME_TEXT[item.machine_outcome].toLowerCase()}`,
  ].filter(Boolean);
  return (
    <div className="grid gap-2.5">
      {item.caller_effect && <Callout tone="warn">{callerEffect(item.caller_effect)}</Callout>}
      {item.error_reason && (
        <Callout tone="danger">{ERROR_TEXT[item.error_reason] ?? item.error_reason}</Callout>
      )}
      {item.answer && <Answer item={item} onTurn={onTurn} />}
      <p className="text-xs-400 text-muted-foreground">{facts.join(" · ")}</p>
    </div>
  );
}

function Callout({ tone, children }: { tone: "warn" | "danger"; children: ReactNode }) {
  return (
    <p
      className={cn(
        "border-l-2 py-0.5 pl-2.5 text-xs-400 text-foreground",
        tone === "warn" ? "border-status-warning" : "border-status-danger",
      )}
    >
      {children}
    </p>
  );
}

/** The judge's answer: quotes that take you to their turn, and its reasoning. Each judge has
 * its own answer shape. */
function Answer({ item, onTurn }: { item: EvaluationItem; onTurn?: OnTurn }) {
  const itemKey = item.item_key;
  const answer = item.answer ?? {};
  const reasoning = typeof answer.reasoning === "string" && answer.reasoning && (
    <p key="reasoning" className="text-xs-400 whitespace-pre-wrap text-muted-foreground">
      {answer.reasoning}
    </p>
  );
  if (!passedChecks(item)) return reasoning || null;
  const parts: ReactNode[] = [];
  const evidence = answer.evidence as Quote[] | undefined;
  if (evidence?.length) parts.push(<Quotes key="evidence" quotes={evidence} onTurn={onTurn} />);
  const recorded = answer.record_evidence as { line: number; quote: string }[] | undefined;
  if (recorded?.length) {
    parts.push(
      <ul key="record-evidence" className="grid gap-1">
        {recorded.map((quote, index) => (
          <li key={index} className="flex items-start gap-2 text-xs-400">
            <span className="shrink-0 rounded-sm bg-muted px-1.5 font-mono text-xs-400 text-muted-foreground">
              Record
            </span>
            <q className="min-w-0 font-mono wrap-anywhere">{quote.quote}</q>
          </li>
        ))}
      </ul>,
    );
  }
  if (itemKey === "saved_data") {
    for (const value of checkedValues<SavedValueResult>(item) ?? []) {
      parts.push(<SavedValueRow key={`saved-${value.name}`} value={value} onTurn={onTurn} />);
    }
  }
  if (itemKey === "heard") {
    for (const value of checkedValues<HeardValueResult>(item) ?? []) {
      parts.push(<HeardRow key={`heard-${value.value}`} value={value} onTurn={onTurn} />);
    }
  }
  const absence = answer.absence_turns as { first: number; last: number } | null | undefined;
  if (answer.absence && absence) {
    parts.push(
      <p key="absence" className="text-xs-400 text-muted-foreground">
        Not said in turns {absence.first} to {absence.last}.
      </p>,
    );
  }
  const matched = answer.matched_turns as number[] | undefined;
  if (matched?.length) {
    parts.push(
      <p
        key="matched"
        className="flex flex-wrap items-center gap-1.5 text-xs-400 text-muted-foreground"
      >
        Found in
        {matched.map((turn) => (
          <TurnChip key={turn} turn={turn} onTurn={onTurn} />
        ))}
      </p>,
    );
  }
  if (itemKey === "instructions") {
    for (const [key, name] of INSTRUCTION_PARTS) {
      const part = answer[key] as Part | undefined;
      if (!part || part.verdict === "not_applicable") continue;
      parts.push(
        <div key={key} className="grid gap-1.5 rounded-md border px-2.5 py-2">
          <span className="flex items-center gap-1.5 text-xs-500">
            <OutcomeIcon
              outcome={part.verdict === "pass" ? "pass" : "fail"}
              className="size-3.5"
              decorative
            />
            {name} {part.verdict === "pass" ? "kept" : "not kept"}
          </span>
          {part.call_quote && <Quotes quotes={[part.call_quote]} onTurn={onTurn} />}
          {part.instruction_quote && (
            <blockquote className="border-l-2 pl-2 text-xs-400 text-muted-foreground">
              Instruction: {part.instruction_quote}
            </blockquote>
          )}
          {part.reasoning && <p className="text-xs-400 text-muted-foreground">{part.reasoning}</p>}
        </div>,
      );
    }
  }
  const contradictions = answer.contradictions as
    | { call_quote: Quote; document: string; document_quote: string; reasoning?: string }[]
    | undefined;
  for (const [index, found] of (contradictions ?? []).entries()) {
    parts.push(
      <div key={`contradiction-${index}`} className="grid gap-1.5 rounded-md border px-2.5 py-2">
        <Quotes quotes={[found.call_quote]} onTurn={onTurn} />
        <blockquote className="border-l-2 pl-2 text-xs-400 text-muted-foreground">
          {found.document}: {found.document_quote}
        </blockquote>
        {found.reasoning && <p className="text-xs-400 text-muted-foreground">{found.reasoning}</p>}
      </div>,
    );
  }
  const findings = answer.findings as { turn: number; finding: string }[] | undefined;
  if (findings?.length) {
    parts.push(
      <ul key="findings" className="grid gap-1.5">
        {findings.map((found, index) => (
          <li key={index} className="flex items-start gap-2 text-xs-400">
            <TurnChip turn={found.turn} onTurn={onTurn} />
            <span className="min-w-0">{found.finding}</span>
          </li>
        ))}
      </ul>,
    );
  }
  if (answer.gate) {
    parts.push(
      <p key="gate" className="text-xs-400 text-muted-foreground">
        Not judged: the agent did not speak.
      </p>,
    );
  }
  if (reasoning) parts.push(reasoning);
  return <div className="grid gap-2">{parts}</div>;
}

const SAVED_OUTCOME: Record<SavedValueResult["result"], Outcome> = {
  matches: "pass",
  contradicts: "fail",
  not_checkable: "not_applicable",
};

const SAVED_TEXT: Record<SavedValueResult["result"], string> = {
  matches: "Matches",
  contradicts: "Does not match",
  not_checkable: "Not checkable",
};

function SavedValueRow({ value, onTurn }: { value: SavedValueResult; onTurn?: OnTurn }) {
  return (
    <div className="grid gap-1.5 rounded-md border px-2.5 py-2">
      <span className="flex flex-wrap items-center gap-1.5 text-xs-500">
        <OutcomeIcon outcome={SAVED_OUTCOME[value.result]} className="size-3.5" decorative />
        <span className="font-mono">{value.name}</span>
        <span className="font-normal text-muted-foreground">{SAVED_TEXT[value.result]}</span>
      </span>
      {value.evidence.length > 0 && <Quotes quotes={value.evidence} onTurn={onTurn} />}
      {value.reasoning && <p className="text-xs-400 text-muted-foreground">{value.reasoning}</p>}
    </div>
  );
}

function HeardRow({ value, onTurn }: { value: HeardValueResult; onTurn?: OnTurn }) {
  return (
    <div className="grid gap-1.5 rounded-md border px-2.5 py-2 text-xs-400">
      <span className="flex items-center gap-1.5 text-xs-500">
        <OutcomeIcon
          outcome={value.result === "same" ? "pass" : "fail"}
          className="size-3.5"
          decorative
        />
        {value.value}
        <span className="font-normal text-muted-foreground">
          {value.result === "same"
            ? "Heard as said"
            : value.result === "different"
              ? "Misheard"
              : "Not heard"}
        </span>
      </span>
      <span className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-x-2 gap-y-1">
        <span className="text-muted-foreground">Said</span>
        <span className="flex items-start gap-2">
          <TurnChip turn={value.said.turn} onTurn={onTurn} />
          <q className="min-w-0 wrap-anywhere">{value.said.quote}</q>
        </span>
        <span className="text-muted-foreground">Heard</span>
        <span className="min-w-0 wrap-anywhere">
          {value.heard ? <q>{value.heard.quote}</q> : "Nothing"}
        </span>
      </span>
    </div>
  );
}

function Quotes({ quotes, onTurn }: { quotes: Quote[]; onTurn?: OnTurn }) {
  return (
    <ul className="grid gap-1">
      {quotes.map((quote, index) => (
        <li key={index} className="flex items-start gap-2 text-xs-400">
          <TurnChip turn={quote.turn} onTurn={onTurn} />
          <q className="min-w-0 wrap-anywhere">{quote.quote}</q>
        </li>
      ))}
    </ul>
  );
}

/** A turn number that takes you to the turn in the transcript. */
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
        "outline-none transition-colors duration-150 hover:bg-foreground hover:text-background focus-visible:ring-2 focus-visible:ring-ring/50 active:scale-95",
      )}
    >
      T{turn}
    </button>
  );
}
