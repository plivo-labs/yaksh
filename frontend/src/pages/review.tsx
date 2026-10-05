import { KeyRound } from "lucide-react";
import { type SubmitEvent, useRef, useState } from "react";
import { Link, NavLink, Outlet, useParams, useSearchParams } from "react-router";

import { TokenGate } from "@/app/token";
import { useDarkMode } from "@/app/use-dark-mode";
import { useToken } from "@/app/use-token";
import { type OnTurn, ItemResult, VerdictLabel, type VerdictKind } from "@/components/call-results";
import { Panel, PanelHeader } from "@/components/panel";
import type { PlayerHandle } from "@/components/recording-player";
import { RelativeTime } from "@/components/relative-time";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { VerdictPill } from "@/components/verdict-ui";
import { LABELER_TOKEN } from "@/lib/api";
import { useReview, useReviewQueue, useSaveLabel } from "@/lib/queries";
import { turnStart } from "@/lib/turns";
import {
  type EvaluationItem,
  LABEL_ANSWERS,
  LABEL_REASONS,
  type LabelAnswer,
  type LabelReason,
  NEEDS_REASON,
  type ReviewConversation,
  type ReviewItem,
  VERDICT_TEXT,
  type Verdict,
} from "@/lib/types";
import { CallPane, ScenarioCard, type ShownTurn } from "@/pages/conversation";

/** The review screen, for labelers. It holds a labeler's token, which opens only the review
 * routes, so it stands outside the console and its API token. */
export function ReviewShell() {
  const [token, setToken] = useToken(LABELER_TOKEN);
  useDarkMode();
  if (!token) {
    return (
      <TokenGate
        title="Labeler token"
        description="A labeler's token, made with POST /api/v1/labelers. It opens only the review screen."
        onToken={setToken}
      />
    );
  }
  return (
    <TooltipProvider delay={500}>
      <div className="flex h-svh flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b px-6">
          <NavLink
            to="/review"
            className="flex items-center gap-2 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            <img src="/favicon.svg" alt="" className="size-7" />
            <span className="text-h4-500">Review</span>
          </NavLink>
          <Button variant="ghost" size="sm" onClick={() => setToken("")}>
            <KeyRound />
            Change token
          </Button>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <Outlet />
        </main>
      </div>
    </TooltipProvider>
  );
}

export function ReviewQueuePage() {
  const queue = useReviewQueue();
  return (
    <Panel className="mx-auto max-w-3xl overflow-hidden">
      <PanelHeader title="Audit queue" />
      <p className="border-b px-5 py-2.5 text-xs text-muted-foreground">
        Calls picked at random to measure the judges. Your labels on their judged items are blind:
        each machine result shows after you save your label. Label every judged item of a call to
        see its verdicts.
      </p>
      {queue.isPending ? (
        <div className="grid gap-2 p-5">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : queue.isError ? (
        <p role="alert" className="px-5 py-4 text-sm text-status-danger">
          Could not load the queue: {queue.error.message}
        </p>
      ) : queue.data.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">Nothing to label now.</p>
      ) : (
        <ul className="divide-y">
          {queue.data.map((entry) => (
            <li key={entry.conversation_id}>
              <Link
                to={`/review/${entry.conversation_id}`}
                className="flex items-center justify-between gap-4 px-5 py-3.5 outline-none transition-colors duration-150 hover:bg-muted/60 focus-visible:bg-muted/60"
              >
                <span className="grid min-w-0 gap-0.5">
                  <span className="truncate text-s-500">{entry.scenario_name}</span>
                  <span className="text-xs text-muted-foreground">
                    Ended <RelativeTime iso={entry.ended_at} />
                  </span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {entry.labeled} of {entry.items} labeled
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function ReviewPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  /** The labeler came from the machine's results, as from the conversation page. */
  const seen = params.get("seen") === "1";
  const review = useReview(id, seen);
  const player = useRef<PlayerHandle>(null);
  const [shown, setShown] = useState<ShownTurn | null>(null);
  if (review.isPending) return <Skeleton className="h-full w-full" />;
  if (review.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the call</AlertTitle>
        <AlertDescription>{review.error.message}</AlertDescription>
      </Alert>
    );
  }
  const data = review.data;
  const conversation = data.conversation;
  const playTurn = (turn: number) => {
    setShown({ index: turn - 1 });
    const at = turnStart(conversation, turn);
    if (conversation.recording_url && at !== null) player.current?.playFrom(at);
  };
  return (
    <div className="flex h-full flex-col gap-4">
      <div className="grid shrink-0 gap-1">
        <h1 className="truncate text-h3-500">{conversation.scenario_name}</h1>
        <p className="text-s-400 text-muted-foreground">
          {data.lane === "audit"
            ? "Audit call: your labels on its judged items are blind and measure the judges."
            : "Ad hoc: your labels change this call's results but do not measure the judges."}
        </p>
      </div>
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-h-0">
          <CallPane conversation={conversation} player={player} start={0} shown={shown} />
        </div>
        <ScrollArea className="min-h-0">
          <div className="flex flex-col gap-6 p-px pr-4">
            <Verdicts verdicts={data.verdicts} />
            <Card>
              <CardHeader>
                <CardTitle>Items</CardTitle>
                <CardDescription>
                  Answer each item from the call. A fail, can't tell or blocked says what went
                  wrong.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-4">
                  {data.items.map((item) => (
                    <ItemLabel
                      key={item.id}
                      item={item}
                      conversationId={id}
                      seen={seen}
                      onTurn={playTurn}
                    />
                  ))}
                </ul>
              </CardContent>
            </Card>
            <ScenarioCard name={conversation.scenario_name} scenario={conversation.scenario} />
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}

function Verdicts({ verdicts }: { verdicts: ReviewConversation["verdicts"] }) {
  if (verdicts === null) {
    return (
      <p className="text-sm text-muted-foreground">
        The call's verdicts show when you have labeled every judged item.
      </p>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Verdicts</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <VerdictLine
            kind="scenario"
            machine={verdicts.scenario_verdict}
            effective={verdicts.effective_scenario_verdict}
          />
          <VerdictLine
            kind="conversation"
            machine={verdicts.conversation_verdict}
            effective={verdicts.effective_conversation_verdict}
          />
        </dl>
      </CardContent>
    </Card>
  );
}

function VerdictLine({
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
    <div className="grid gap-1">
      <dt className="justify-self-start">
        <VerdictLabel kind={kind} />
      </dt>
      <dd className="grid justify-items-start gap-1">
        <VerdictPill verdict={effective} />
        <span className="text-xs text-muted-foreground">
          Machine: {VERDICT_TEXT[machine].toLowerCase()}
        </span>
      </dd>
    </div>
  );
}

const ANSWER_TEXT = Object.fromEntries(LABEL_ANSWERS.map((item) => [item.value, item.label]));
const REASON_TEXT = Object.fromEntries(LABEL_REASONS.map((item) => [item.value, item.label]));

/** Whether a label gives the machine's outcome, the way a verdict counts them: "can't tell"
 * because of a hidden action and "not applicable" count the same. */
function agrees(answer: LabelAnswer, reason: LabelReason | null, machine: EvaluationItem): boolean {
  const counted = (outcome: string, hidden: boolean) =>
    outcome === "unsure" && hidden ? "not_applicable" : outcome;
  const given = answer === "cannot_tell" ? "unsure" : answer;
  return (
    counted(given, reason === "hidden_action") ===
    counted(machine.machine_outcome, machine.unsure_kind === "hidden_action")
  );
}

function ItemLabel({
  item,
  conversationId,
  seen,
  onTurn,
}: {
  item: ReviewItem;
  conversationId: string;
  seen: boolean;
  onTurn?: OnTurn;
}) {
  const save = useSaveLabel(conversationId, seen);
  const [editing, setEditing] = useState(item.label === null);
  const [answer, setAnswer] = useState<LabelAnswer | null>(item.label?.answer ?? null);
  const [reason, setReason] = useState<LabelReason | null>(item.label?.reason ?? null);
  const [note, setNote] = useState(item.label?.note ?? "");
  const [submitted, setSubmitted] = useState(false);
  const noteMissing = reason === "other" && !note.trim();
  /** A label that names a problem, or that overturns the answer in view, says why. */
  const reasonNeeded =
    answer !== null &&
    (NEEDS_REASON.includes(answer) ||
      (item.machine !== null && !agrees(answer, reason, item.machine)));
  const reasonMissing = reasonNeeded && reason === null;
  const ready = answer !== null && !reasonMissing && !noteMissing;
  const field = `item-${item.id}`;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!ready) return;
    save.mutate(
      { itemId: item.id, label: { answer, reason, note: note.trim() || null } },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <li className="grid gap-3 rounded-md border px-4 py-3 text-sm">
      <span className="wrap-anywhere">{item.subject}</span>
      {item.label && !editing ? (
        <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
          <span>
            Your label: {ANSWER_TEXT[item.label.answer]}
            {item.label.reason && `, ${REASON_TEXT[item.label.reason]}`}
            {item.label.note && `: ${item.label.note}`}
          </span>
          {item.machine && (
            <span
              className={
                agrees(item.label.answer, item.label.reason, item.machine)
                  ? "text-status-success-text"
                  : "text-status-warning-text"
              }
            >
              {agrees(item.label.answer, item.label.reason, item.machine)
                ? "Agrees with the machine"
                : "Differs from the machine"}
            </span>
          )}
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0 text-xs"
            onClick={() => setEditing(true)}
          >
            Change
          </Button>
        </p>
      ) : (
        <form noValidate onSubmit={submit} className="grid gap-3">
          <div
            role="group"
            aria-label="Your answer"
            aria-describedby={submitted && answer === null ? `${field}-answer-error` : undefined}
            className="flex flex-wrap gap-1.5"
          >
            {LABEL_ANSWERS.map((option) => (
              <Button
                key={option.value}
                type="button"
                size="sm"
                aria-pressed={answer === option.value}
                variant={answer === option.value ? "default" : "outline"}
                onClick={() => setAnswer(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
          {submitted && answer === null && (
            <FieldError id={`${field}-answer-error`}>Choose an answer.</FieldError>
          )}
          <Field>
            <FieldLabel htmlFor={`${field}-reason`}>
              Reason{answer !== null && !reasonNeeded ? " (optional)" : ""}
            </FieldLabel>
            <Select
              items={LABEL_REASONS}
              value={reason}
              onValueChange={(value) => setReason(value as LabelReason)}
            >
              <SelectTrigger
                id={`${field}-reason`}
                className="w-full"
                aria-invalid={submitted && reasonMissing}
                aria-describedby={submitted && reasonMissing ? `${field}-reason-error` : undefined}
              >
                <SelectValue placeholder="Choose a reason" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {LABEL_REASONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {reason && (
              <FieldDescription className="flex flex-wrap items-baseline gap-x-2">
                {LABEL_REASONS.find((option) => option.value === reason)?.example}
                {!reasonNeeded && (
                  <Button
                    type="button"
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-xs"
                    onClick={() => setReason(null)}
                  >
                    Clear
                  </Button>
                )}
              </FieldDescription>
            )}
            {submitted && reasonMissing && (
              <FieldError id={`${field}-reason-error`}>
                {item.machine && answer && !NEEDS_REASON.includes(answer)
                  ? "Your answer differs from the machine's: choose why."
                  : "Choose what went wrong."}
              </FieldError>
            )}
          </Field>
          <Field>
            <FieldLabel htmlFor={`${field}-note`}>
              Note{reason === "other" ? "" : " (optional)"}
            </FieldLabel>
            <Input
              id={`${field}-note`}
              maxLength={2000}
              value={note}
              aria-invalid={submitted && noteMissing}
              onChange={(event) => setNote(event.target.value)}
            />
            {submitted && noteMissing && <FieldError>The reason other needs a note.</FieldError>}
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" size="sm" disabled={save.isPending}>
              {save.isPending && <Spinner />}
              Save label
            </Button>
            {item.label && (
              <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            )}
            {item.blind && (
              <span className="text-xs text-muted-foreground">
                The machine result shows after you save.
              </span>
            )}
          </div>
          {save.error && <FieldError>{save.error.message}</FieldError>}
        </form>
      )}
      {item.machine ? (
        <ul className="border-t pt-3">
          <ItemResult item={item.machine} onTurn={onTurn} machineOnly />
        </ul>
      ) : (
        !item.blind && (
          <p className="text-xs text-muted-foreground">
            The machine result shows when you have labeled every judged item.
          </p>
        )
      )}
    </li>
  );
}
