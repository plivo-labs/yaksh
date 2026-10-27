import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BAND_FILL, duration, latency, percent, responseBand, seconds } from "@/lib/format";
import { useConversationEvaluation } from "@/lib/queries";
import { inOrder, STAGE_FILL, stepLabel, stepStage } from "@/lib/reply-steps";
import {
  type CaptureFaults,
  type ConversationEvaluation,
  type EvaluationState,
  FLAG_TEXT,
  type Transport,
  evaluationPending,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type Metrics = ConversationEvaluation["metrics"];

/** What the evaluator computed for the call, once it is done: the agent first, then Yaksh's
 * caller, then the call itself. */
export function CallMetricsCard({
  conversationId,
  evaluation,
  transport,
}: {
  conversationId: string;
  evaluation: EvaluationState | null;
  transport: Transport;
}) {
  const found = useConversationEvaluation(conversationId, evaluation);
  if (evaluation === null) return null;
  // Metrics read earlier stay on screen when a later read fails.
  const failedToLoad = found.isError && (
    <p role="alert" className="text-s-400 text-status-danger">
      Could not load the metrics: {found.error.message}
    </p>
  );
  if (evaluation === "done" && found.data) {
    return (
      <div className="grid gap-3">
        {failedToLoad}
        <MetricCards metrics={found.data.metrics} transport={transport} />
      </div>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Conversation metrics</CardTitle>
        {evaluationPending(evaluation) && (
          <CardDescription>Measuring the conversation.</CardDescription>
        )}
        {evaluation === "failed" && (
          <CardDescription className="text-status-danger wrap-anywhere">
            The measurement failed{found.data?.failure ? `: ${found.data.failure}` : "."}
          </CardDescription>
        )}
        {failedToLoad}
      </CardHeader>
    </Card>
  );
}

function MetricCards({ metrics, transport }: { metrics: Metrics; transport: Transport }) {
  const flags = [...new Set(Object.values(metrics).flatMap((metric) => metric.flags))];
  return (
    <div className="grid gap-3">
      {flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {flags.map((flag) => (
            <Badge key={flag} variant="tag">
              {FLAG_TEXT[flag] ?? flag}
            </Badge>
          ))}
        </div>
      )}
      <AgentCard metrics={metrics} />
      <CallerCard metrics={metrics} transport={transport} />
      <CallCard metrics={metrics} />
    </div>
  );
}

function AgentCard({ metrics }: { metrics: Metrics }) {
  const { response_time, turn_taking, speaking, agent_repetition } = metrics;
  const runs = agent_repetition?.value.runs ?? [];
  if (!response_time && !turn_taking && !speaking && runs.length === 0) return null;
  const waits = response_time?.value.replies.map((reply) => reply.speech_ms - reply.start_ms);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent response time</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 text-p-400">
        {response_time && (
          <Stats>
            <Stat label="p50" value={latencyOrDash(response_time.value.p50_ms)} />
            <Stat label="p90" value={latencyOrDash(response_time.value.p90_ms)} />
            <Stat label="Longest wait" value={latencyOrDash(turn_taking?.value.longest_wait_ms)} />
            <Stat label="Replies" value={String(response_time.value.replies.length)} />
          </Stats>
        )}
        {waits && waits.length > 0 && <ReplyBars waits={waits} />}
        {turn_taking?.value.longest_wait_ms != null && (
          <p className="text-s-400 text-muted-foreground">
            Waits of 3s, 5s and 10s or more:{" "}
            {["3000", "5000", "10000"]
              .map((limit) => turn_taking.value.at_least_ms[limit])
              .join(", ")}
          </p>
        )}
        {(turn_taking || speaking) && (
          <dl className="grid grid-cols-2 gap-3 border-t pt-3">
            {turn_taking && (
              <>
                <Line label="Turns that expected an answer">
                  {turn_taking.value.expected}, {turn_taking.value.unanswered} unanswered
                </Line>
                <Line label="Spoke over the caller">{turn_taking.value.talked_over}</Line>
              </>
            )}
            {speaking && (
              <>
                <Line label="Agent's share of the speech">
                  {speaking.value.agent_share === null
                    ? "No speech"
                    : percent(speaking.value.agent_share)}
                </Line>
                <Line label="Longest monologue">
                  {duration(speaking.value.longest_monologue_ms)}
                </Line>
              </>
            )}
          </dl>
        )}
        {runs.length > 0 && (
          <dl className="grid gap-3">
            {runs.map((run) => (
              <Line key={run.at_ms} label={`Said ${run.count} times in a row`}>
                {run.text}
              </Line>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

/** One bar per reply in call order, in the colour of its band, with the band limits drawn
 * across. A talk-over has no wait: a short grey bar. */
/** The response bands' limits, drawn across the bars. */
const LIMITS = [1000, 2000];

function ReplyBars({ waits }: { waits: number[] }) {
  // A wait over the top fills the bar; its title keeps the value.
  const top = Math.min(Math.max(2500, ...waits), 5000);
  const at = (ms: number) => `${(Math.min(ms, top) / top) * 100}%`;
  return (
    <figure className="grid gap-1.5">
      <figcaption className="text-xs-400 text-muted-foreground">
        Each reply, in call order
      </figcaption>
      {/* A long call scrolls sideways rather than squeezing its bars; the limits' labels stay
      in view above the scrolled plot. */}
      <div className="relative">
        <div className="overflow-x-auto">
          <div
            role="img"
            aria-label={`Agent response time per reply: ${waits.map((ms) => (ms < 0 ? "talked over" : latency(ms))).join(", ")}`}
            className="relative flex h-20 items-end gap-1 border-b"
            style={{ minWidth: `${waits.length * 0.5}rem` }}
          >
            {waits.map((ms, index) => (
              <span
                key={index}
                title={`Reply ${index + 1}: ${ms < 0 ? "talked over" : latency(ms)}`}
                className={cn(
                  "max-w-6 min-w-1 flex-1 rounded-t-xs",
                  ms < 0 ? "h-0.5 bg-chart-neutral" : BAND_FILL[responseBand(ms)],
                )}
                style={ms < 0 ? undefined : { height: at(ms) }}
              />
            ))}
            {LIMITS.map((limit) => (
              <span
                key={limit}
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 border-t border-dashed border-border"
                style={{ bottom: at(limit) }}
              />
            ))}
          </div>
        </div>
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-20">
          {LIMITS.map((limit) => (
            <span
              key={limit}
              className="absolute right-0 translate-y-1/2 bg-card pl-1 text-xxs-400 text-muted-foreground"
              style={{ bottom: at(limit) }}
            >
              {seconds(limit)}
            </span>
          ))}
        </div>
      </div>
    </figure>
  );
}

function CallerCard({ metrics, transport }: { metrics: Metrics; transport: Transport }) {
  const settings = metrics.usage?.value.settings;
  const consumed = metrics.usage?.value.usage;
  const replies = metrics.caller_reply_time?.value;
  if (!settings && !consumed && !replies) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Caller</CardTitle>
        {settings && (
          <CardDescription>
            Language model {settings.llm_model}
            {settings.reasoning_effort && `, ${settings.reasoning_effort} effort`}
            {settings.scenario_model && " (set by the scenario)"}
            {settings.stt_model && (
              <>
                , speech to text {settings.stt_model}
                {settings.stt_language && ` (${settings.stt_language})`}
              </>
            )}
            {settings.tts_model && `, text to speech ${settings.tts_model}`}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="grid gap-4 text-p-400">
        {replies ? (
          <>
            <Stats>
              <Stat label="Reply p50" value={latency(replies.p50_ms)} />
              <Stat label="Reply p90" value={latency(replies.p90_ms)} />
              <Stat label="Replies" value={String(replies.replies)} />
            </Stats>
            <StepBar steps={replies.steps} />
            <StepTable steps={replies.steps} />
          </>
        ) : (
          transport === "phone" && (
            <p className="text-s-400 text-muted-foreground">Reply time not measured.</p>
          )
        )}
        {consumed && (
          <p className="text-s-400 text-muted-foreground">
            {[
              consumed.llm_prompt_tokens !== null && `${consumed.llm_prompt_tokens} prompt tokens`,
              consumed.llm_completion_tokens !== null &&
                `${consumed.llm_completion_tokens} output tokens`,
              consumed.tts_characters !== null && `${consumed.tts_characters} characters spoken`,
              consumed.stt_audio_seconds !== null &&
                `${Math.round(consumed.stt_audio_seconds)}s of audio transcribed`,
            ]
              .filter(Boolean)
              .join(", ") || "No usage reported"}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

type Step = { key: string; p50_ms: number; p90_ms: number };

/** Where a typical reply's time goes: each part's p50, as a share of their sum. */
function StepBar({ steps }: { steps: Step[] }) {
  const parts = inOrder(steps.map((step): [string, Step] => [step.key, step])).filter(
    ([, step]) => step.p50_ms > 0,
  );
  if (parts.length === 0) return null;
  return (
    <figure className="grid gap-1.5">
      <figcaption className="text-xs-400 text-muted-foreground">
        Where a typical reply's time goes (p50 of each part)
      </figcaption>
      <div
        role="img"
        aria-label={parts
          .map(([key, step]) => `${stepLabel(key)} ${latency(step.p50_ms)}`)
          .join(", ")}
        className="flex h-5 gap-0.5 overflow-hidden rounded-sm"
      >
        {parts.map(([key, step]) => (
          <span
            key={key}
            title={`${stepLabel(key)}: ${latency(step.p50_ms)}`}
            className={STAGE_FILL[stepStage(key)]}
            style={{ flex: `${step.p50_ms} 0 0` }}
          />
        ))}
      </div>
    </figure>
  );
}

function StepTable({ steps }: { steps: Step[] }) {
  return (
    <table className="text-s-400 tabular-nums">
      <thead className="text-xs-400 text-muted-foreground">
        <tr>
          <th className="py-1 text-left font-normal">Part</th>
          <th className="py-1 text-right font-normal">p50</th>
          <th className="py-1 text-right font-normal">p90</th>
        </tr>
      </thead>
      <tbody>
        {inOrder(steps.map((step): [string, Step] => [step.key, step])).map(([key, step]) => (
          <tr key={key} className="border-t">
            <td className="py-1.5">
              <span className="flex items-center gap-2">
                <span className={cn("size-2 rounded-xs", STAGE_FILL[stepStage(key)])} />
                {stepLabel(key)}
              </span>
            </td>
            <td className="py-1.5 text-right">{latency(step.p50_ms)}</td>
            <td className="py-1.5 text-right text-muted-foreground">{latency(step.p90_ms)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CallCard({ metrics }: { metrics: Metrics }) {
  const { usage, capture_faults } = metrics;
  const problems = capture_faults && capture_faults.flags.length > 0;
  if (!usage && !problems) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Call</CardTitle>
        {usage && <CardDescription>Times from the start of the conversation.</CardDescription>}
      </CardHeader>
      <CardContent className="grid gap-3 text-p-400">
        {usage && (
          <dl className="grid grid-cols-3 gap-3 tabular-nums">
            <Line label="Ringing at">{since(usage.value.ringing_ms)}</Line>
            <Line label="Answered at">{since(usage.value.answered_ms)}</Line>
            <Line label="Audio at">{since(usage.value.stream_opened_ms)}</Line>
            {usage.value.bill_duration_s != null && (
              <Line label="Billed by Plivo">{usage.value.bill_duration_s}s</Line>
            )}
          </dl>
        )}
        {problems && (
          <dl>
            <Line label="Record problems">{faultsText(capture_faults.value)}</Line>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

/** A time from the start of the conversation, or a dash when it did not happen. */
function since(ms: number | null): string {
  return ms === null ? "–" : seconds(ms);
}

function latencyOrDash(ms: number | null | undefined): string {
  return ms == null ? "–" : latency(ms);
}

/** The record's problems as counts. The flags above name them; these say how many. */
function faultsText(faults: CaptureFaults): string {
  if ("incomplete_record" in faults) {
    return "The worker stopped before it saved the conversation in full.";
  }
  const found = [
    faults.caller_error.length > 0 && `caller error: ${faults.caller_error.join("; ")}`,
    faults.unconfirmed_caller_turns > 0 &&
      `${faults.unconfirmed_caller_turns} caller turns not confirmed as played`,
    faults.media_gaps > 0 &&
      `${faults.media_gaps} gaps in the agent's media, ${faults.media_gap_ms}ms in all`,
    faults.worker_stall && `the worker paused for ${faults.worker_stall.max_ms}ms`,
  ]
    .filter(Boolean)
    .join(", ");
  if (!found) return "A recording is missing, or no media came from the agent's side.";
  return found[0].toUpperCase() + found.slice(1);
}

function Stats({ children }: { children: ReactNode }) {
  return <dl className="flex flex-wrap gap-x-7 gap-y-2 tabular-nums">{children}</dl>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="text-h3-500">{value}</dd>
    </div>
  );
}

function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="wrap-anywhere">{children}</dd>
    </div>
  );
}
