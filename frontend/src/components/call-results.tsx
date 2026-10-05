import { type ReactNode, useState } from "react";
import { Link } from "react-router";

import { StatusLabel } from "@/components/status-label";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { percent } from "@/lib/format";
import { useConversationEvaluation } from "@/lib/queries";
import { OUTCOME_TONE, VERDICT_TONE } from "@/lib/status";
import {
  DECIDED_BY_TEXT,
  ERROR_TEXT,
  type EvaluationItem,
  type EvaluationState,
  OUTCOME_TEXT,
  UNSURE_TEXT,
  VERDICT_TEXT,
  type Verdict,
  evaluationPending,
} from "@/lib/types";

/** Plays the call from the start of that turn, counted from 1. */
export type OnTurn = (turn: number) => void;

const GROUPS: { title: string; matches: (key: string) => boolean }[] = [
  { title: "Criteria", matches: (key) => key.startsWith("criterion-") },
  { title: "Agent rules", matches: (key) => key.startsWith("rule-") },
  {
    title: "Reports",
    matches: (key) => key === "instructions" || key === "hallucination" || key === "caller_check",
  },
];

/** What the judges found in the call: its verdicts, and each criterion, agent rule and report
 * with its quotes. */
export function CallResultsCard({
  conversationId,
  evaluation,
  onTurn,
}: {
  conversationId: string;
  evaluation: EvaluationState | null;
  onTurn?: OnTurn;
}) {
  const found = useConversationEvaluation(conversationId, evaluation);
  if (evaluation === null || evaluation === "failed") return null;
  const data = found.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Results</CardTitle>
        {data && data.scenario_verdict !== null && (
          <CardAction>
            <Link
              to={`/review/${conversationId}?seen=1`}
              className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              Label
            </Link>
          </CardAction>
        )}
        {evaluationPending(evaluation) && <CardDescription>Judging the call.</CardDescription>}
        {found.isError && (
          <CardDescription role="alert" className="text-status-danger">
            Could not load the results: {found.error.message}
          </CardDescription>
        )}
        {data && data.scenario_verdict === null && (
          <CardDescription>
            Not judged. The judges read completed calls that no one stopped, when the server has a
            judge model.
          </CardDescription>
        )}
      </CardHeader>
      {data && (data.scenario_verdict !== null || data.items.length > 0) && (
        <CardContent className="grid gap-5 text-sm">
          {data.scenario_verdict !== null && (
            <dl className="grid grid-cols-2 gap-3">
              <VerdictFact
                label="Scenario"
                machine={data.scenario_verdict}
                effective={data.effective_scenario_verdict}
              />
              <VerdictFact
                label="With deciding rules"
                machine={data.conversation_verdict}
                effective={data.effective_conversation_verdict}
              />
            </dl>
          )}
          {GROUPS.map(({ title, matches }) => {
            const items = data.items.filter((item) => matches(item.item_key));
            if (items.length === 0) return null;
            return (
              <section key={title} className="grid gap-3">
                <h3 className="text-xs text-muted-foreground">{title}</h3>
                <ul className="grid gap-4">
                  {items.map((item) => (
                    <ItemResult key={item.item_key} item={item} onTurn={onTurn} />
                  ))}
                </ul>
              </section>
            );
          })}
        </CardContent>
      )}
    </Card>
  );
}

function VerdictFact({
  label,
  machine,
  effective,
}: {
  label: string;
  machine: Verdict | null;
  effective: Verdict | null;
}) {
  if (machine === null || effective === null) return null;
  return (
    <div className="grid gap-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="grid gap-0.5">
        <StatusLabel tone={VERDICT_TONE[effective]}>{VERDICT_TEXT[effective]}</StatusLabel>
        {effective !== machine && (
          <span className="text-xs text-muted-foreground">
            Labels changed it from {VERDICT_TEXT[machine].toLowerCase()}
          </span>
        )}
      </dd>
    </div>
  );
}

/** One item: its outcome after labels, who decided it, and what the judge quoted. */
export function ItemResult({
  item,
  onTurn,
  machineOnly = false,
}: {
  item: EvaluationItem;
  onTurn?: OnTurn;
  /** Show what the machine decided, not the outcome after labels: for a labeler comparing. */
  machineOnly?: boolean;
}) {
  const outcome = machineOnly ? item.machine_outcome : item.effective_outcome;
  const kind = machineOnly ? item.unsure_kind : item.effective_unsure_kind;
  return (
    <li className="grid gap-1.5">
      <div className="flex items-start justify-between gap-3">
        {machineOnly ? (
          <span className="text-xs text-muted-foreground">The machine's answer</span>
        ) : (
          <span className="min-w-0 wrap-anywhere">{item.subject}</span>
        )}
        <StatusLabel tone={OUTCOME_TONE[outcome]}>{OUTCOME_TEXT[outcome]}</StatusLabel>
      </div>
      <p className="text-xs text-muted-foreground">
        {decidedBy(item)}
        {item.role === "deciding" && item.item_key.startsWith("rule-") && ", counts in the verdict"}
        {outcome === "unsure" && kind && `; ${UNSURE_TEXT[kind]}`}
        {!machineOnly &&
          outcome !== item.machine_outcome &&
          `; labels changed it from ${OUTCOME_TEXT[item.machine_outcome].toLowerCase()}`}
      </p>
      {item.caller_effect && (
        <p className="text-xs text-status-warning-text">{callerEffect(item.caller_effect)}</p>
      )}
      {item.error_reason && (
        <p className="text-xs text-status-danger">
          {ERROR_TEXT[item.error_reason] ?? item.error_reason}
        </p>
      )}
      {item.answer && <Answer itemKey={item.item_key} answer={item.answer} onTurn={onTurn} />}
    </li>
  );
}

/** What the caller check found for a criterion, by who caused it. */
function callerEffect(found: NonNullable<EvaluationItem["caller_effect"]>): string {
  if (found.blame === null) {
    return "The caller check failed on a call that a test limit ended, so this is not scored.";
  }
  if (found.owner === "test_settings")
    return `The test's turn or time limit cut this off: ${found.effect}`;
  if (found.owner === "scenario") return `The scenario cannot pass as written: ${found.effect}`;
  const how = found.blame === "likely" ? "likely changed" : "may have changed";
  return `Truman's caller ${how} this: ${found.effect}`;
}

function decidedBy(item: EvaluationItem): string {
  const meets = item.jev_probabilities?.meets;
  if (item.decided_by === "jev" && meets !== undefined) return `Jev, ${percent(meets)} sure`;
  return DECIDED_BY_TEXT[item.decided_by];
}

type Quote = { turn: number; quote: string };

const INSTRUCTION_PARTS = [
  ["objective", "Goal"],
  ["procedure", "Steps"],
  ["boundary", "Limits"],
] as const;

/** The judge's answer, as quotes that play the call from their turn, and its reasoning on
 * request. Each judge has its own answer shape. */
function Answer({
  itemKey,
  answer,
  onTurn,
}: {
  itemKey: string;
  answer: Record<string, unknown>;
  onTurn?: OnTurn;
}) {
  const parts: ReactNode[] = [];
  const evidence = answer.evidence as Quote[] | undefined;
  if (evidence?.length) {
    parts.push(<Quotes key="evidence" quotes={evidence} onTurn={onTurn} />);
  }
  const absence = answer.absence_turns as { first: number; last: number } | null | undefined;
  if (answer.absence && absence) {
    parts.push(
      <p key="absence" className="text-xs text-muted-foreground">
        Not said in turns {absence.first} to {absence.last}.
      </p>,
    );
  }
  const matched = answer.matched_turns as number[] | undefined;
  if (matched?.length) {
    parts.push(
      <p key="matched" className="flex flex-wrap gap-x-2 text-xs text-muted-foreground">
        Found in
        {matched.map((turn) => (
          <TurnLink key={turn} turn={turn} onTurn={onTurn} />
        ))}
      </p>,
    );
  }
  if (itemKey === "instructions") {
    for (const [part, name] of INSTRUCTION_PARTS) {
      const found = answer[part] as
        | { verdict: string; call_quote: Quote | null; instruction_quote: string | null }
        | undefined;
      if (!found || found.verdict === "not_applicable") continue;
      parts.push(
        <div key={part} className="grid gap-1 text-xs">
          <span className="text-muted-foreground">
            {name}: {found.verdict === "pass" ? "kept" : "not kept"}
          </span>
          {found.call_quote && <Quotes quotes={[found.call_quote]} onTurn={onTurn} />}
          {found.instruction_quote && (
            <blockquote className="border-l-2 pl-2 text-muted-foreground">
              Instruction: {found.instruction_quote}
            </blockquote>
          )}
        </div>,
      );
    }
  }
  const contradictions = answer.contradictions as
    | { call_quote: Quote; document: string; document_quote: string }[]
    | undefined;
  for (const [index, found] of (contradictions ?? []).entries()) {
    parts.push(
      <div key={`contradiction-${index}`} className="grid gap-1 text-xs">
        <Quotes quotes={[found.call_quote]} onTurn={onTurn} />
        <blockquote className="border-l-2 pl-2 text-muted-foreground">
          {found.document}: {found.document_quote}
        </blockquote>
      </div>,
    );
  }
  const findings = answer.findings as { turn: number; finding: string }[] | undefined;
  for (const [index, found] of (findings ?? []).entries()) {
    parts.push(
      <p key={`finding-${index}`} className="text-xs">
        <TurnLink turn={found.turn} onTurn={onTurn} />: {found.finding}
      </p>,
    );
  }
  if (answer.gate) {
    parts.push(
      <p key="gate" className="text-xs text-muted-foreground">
        Not judged: the agent did not speak.
      </p>,
    );
  }
  const reasoning = typeof answer.reasoning === "string" ? answer.reasoning : null;
  return (
    <div className="grid gap-1.5">
      {parts}
      {reasoning && <Reasoning text={reasoning} />}
    </div>
  );
}

function Quotes({ quotes, onTurn }: { quotes: Quote[]; onTurn?: OnTurn }) {
  return (
    <ul className="grid gap-1 text-xs">
      {quotes.map((quote, index) => (
        <li key={index} className="flex gap-2">
          <TurnLink turn={quote.turn} onTurn={onTurn} />
          <q className="min-w-0 wrap-anywhere">{quote.quote}</q>
        </li>
      ))}
    </ul>
  );
}

function TurnLink({ turn, onTurn }: { turn: number; onTurn?: OnTurn }) {
  if (!onTurn) return <span className="shrink-0 font-mono text-muted-foreground">Turn {turn}</span>;
  return (
    <button
      type="button"
      title="Play from this turn"
      onClick={() => onTurn(turn)}
      className="shrink-0 rounded-sm font-mono text-muted-foreground underline decoration-dotted underline-offset-2 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      Turn {turn}
    </button>
  );
}

function Reasoning({ text }: { text: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="grid gap-1">
      <Button
        variant="link"
        size="sm"
        className="h-auto justify-self-start p-0 text-xs"
        aria-expanded={shown}
        onClick={() => setShown(!shown)}
      >
        {shown ? "Hide reasoning" : "Show reasoning"}
      </Button>
      {shown && <p className="text-xs whitespace-pre-wrap text-muted-foreground">{text}</p>}
    </div>
  );
}
