import { type ReactNode, useState } from "react";

import { TRACES_DOCS_URL } from "@/app/nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Explained } from "@/components/verdict-ui";
import {
  BAND_FILL,
  BAND_TEXT,
  clock,
  counted,
  duration,
  latency,
  percent,
  phone,
  responseBand,
  seconds,
} from "@/lib/format";
import { useConversationEvaluation } from "@/lib/queries";
import {
  AGENT_STEPS,
  AGENT_STT_TTFS,
  CALLER_STEPS,
  STAGE_FILL,
  STT_TTFS,
  type StepNames,
} from "@/lib/reply-steps";
import { sttProvider, ttsProvider } from "@/lib/speech-providers";
import { type LineRow, lineRows, stopHint, stopLabel, stoppedSummary } from "@/lib/stops";
import {
  type AgentReplyTimeMetric,
  type ConversationEvaluation,
  type EvaluationState,
  type Reply,
  type Transport,
  type Turn,
  evaluationPending,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type Metrics = ConversationEvaluation["metrics"];

/** What the evaluator computed for the call, once it is done: the agent first, then the
 * conversation, then Yaksh's caller and the call itself. */
export function CallMetricsCard({
  conversationId,
  evaluation,
  transport,
  yakshNumber,
  turns,
  connectedMs,
}: {
  conversationId: string;
  evaluation: EvaluationState | null;
  transport: Transport;
  /** Yaksh's number on the call: the key that the agent's trace can carry. */
  yakshNumber: string | null;
  /** The call's turns: each interruption line's first turn holds its stop. */
  turns: Turn[];
  /** Turn times count from the dial; they show from the connect, as the transcript does. */
  connectedMs: number;
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
        <MetricSections
          metrics={found.data.metrics}
          transport={transport}
          yakshNumber={yakshNumber}
          lines={lineRows(turns)}
          connectedMs={connectedMs}
        />
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

function MetricSections({
  metrics,
  transport,
  yakshNumber,
  lines,
  connectedMs,
}: {
  metrics: Metrics;
  transport: Transport;
  yakshNumber: string | null;
  lines: LineRow[];
  connectedMs: number;
}) {
  const { response_time, agent_reply_time } = metrics;
  const replies = response_time?.value.replies ?? [];
  return (
    <Card>
      <CardContent className="grid text-p-400 [&>section+section]:mt-5 [&>section+section]:border-t [&>section+section]:pt-5">
        {response_time && (
          <section className="grid gap-3">
            <Heading level="title" aside={counted(replies.length, "reply", "replies")}>
              Agent response time
            </Heading>
            <dl className="grid grid-cols-3 gap-3 tabular-nums">
              <BigStat label="p50" ms={response_time.value.p50_ms} />
              <BigStat label="p90" ms={response_time.value.p90_ms} />
              <BigStat label="Longest" ms={longestReply(replies)} />
            </dl>
          </section>
        )}
        {replies.length > 0 && (
          <section className="grid gap-3">
            <Heading aside={<BandLegend />}>Each reply</Heading>
            <ReplyBars replies={replies} />
          </section>
        )}
        {lines.length > 0 && <InterruptionsSection lines={lines} connectedMs={connectedMs} />}
        {agent_reply_time && (
          <AgentParts metric={agent_reply_time.value} yakshNumber={yakshNumber} />
        )}
        <ConversationSection metrics={metrics} />
        <TestRunSection metrics={metrics} transport={transport} />
      </CardContent>
    </Card>
  );
}

function Heading({
  children,
  aside,
  level = "section",
}: {
  children: ReactNode;
  aside?: ReactNode;
  level?: "title" | "section";
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      {level === "title" ? (
        <h2 className="text-h4-500">{children}</h2>
      ) : (
        <h3 className="text-p-500">{children}</h3>
      )}
      {aside && <div className="text-xs-400 text-muted-foreground">{aside}</div>}
    </div>
  );
}

/** A wait in large type, in the colour of its band. */
function BigStat({ label, ms }: { label: string; ms: number | null | undefined }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className={cn("text-h3-500", ms != null && BAND_TEXT[responseBand(ms)])}>
        {ms == null ? "–" : latency(ms)}
      </dd>
    </div>
  );
}

const BANDS = [
  { band: "good", label: "Under 1s" },
  { band: "slow", label: "1–2s" },
  { band: "bad", label: "Over 2s" },
] as const;

function BandLegend() {
  return (
    <ul className="flex gap-3">
      {BANDS.map(({ band, label }) => (
        <li key={band} className="flex items-center gap-1.5">
          <span aria-hidden="true" className={cn("size-2 rounded-xs", BAND_FILL[band])} />
          {label}
        </li>
      ))}
    </ul>
  );
}

/** The longest wait that the agent answered; a talk-over has no wait. */
function longestReply(replies: Reply[]): number | null {
  const waits = replies.map((reply) => reply.speech_ms - reply.start_ms).filter((ms) => ms >= 0);
  return waits.length > 0 ? Math.max(...waits) : null;
}

/** The response bands' limits, drawn across the bars. */
const LIMITS = [1000, 2000];

/** One bar per reply in call order, in the color of its band, with the band limits drawn
 * across. A talk-over has no wait: a short grey bar. */
function ReplyBars({ replies }: { replies: Reply[] }) {
  const waits = replies.map((reply) => reply.speech_ms - reply.start_ms);
  // A wait over the top fills the bar; its title keeps the value.
  const top = Math.min(Math.max(2500, ...waits), 5000);
  const at = (ms: number) => `${(Math.min(ms, top) / top) * 100}%`;
  return (
    <figure className="grid gap-1.5">
      {/* A long call scrolls sideways rather than squeezing its bars; the limits' labels stay
      in view above the scrolled plot. */}
      <div className="relative">
        <div className="overflow-x-auto">
          <div
            role="img"
            aria-label={`Agent response time per reply: ${waits.map((ms) => (ms < 0 ? "talked over" : latency(ms))).join(", ")}`}
            className="relative flex h-24 items-end gap-1 border-b"
            style={{ minWidth: `${waits.length * 0.5}rem` }}
          >
            {waits.map((ms, index) => (
              <span
                key={index}
                title={`Reply ${index + 1} at ${clock(replies[index].speech_ms)}: ${ms < 0 ? "talked over" : latency(ms)}`}
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
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-24">
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
      <figcaption className="flex justify-between font-mono text-xxs-400 text-muted-foreground tabular-nums">
        <span>{clock(replies[0].speech_ms)}</span>
        {replies.length > 1 && <span>{clock(replies[replies.length - 1].speech_ms)}</span>}
      </figcaption>
    </figure>
  );
}

/** The parts of the agent's waits, from its trace of the call; or one line on why there are
 * none. */
function AgentParts({
  metric,
  yakshNumber,
}: {
  metric: AgentReplyTimeMetric;
  yakshNumber: string | null;
}) {
  if (metric.status !== "ok") {
    return (
      <section className="grid gap-2">
        <Heading>Where the agent's time goes</Heading>
        <p className="text-s-400 text-muted-foreground">
          {missingParts(metric, yakshNumber)}{" "}
          <a href={TRACES_DOCS_URL} target="_blank" rel="noreferrer" className="underline">
            How to send traces
          </a>
        </p>
      </section>
    );
  }
  return (
    <section className="grid gap-3">
      <Heading aside={`${metric.usable} of ${counted(metric.eligible, "reply", "replies")} traced`}>
        Where the agent's time goes
      </Heading>
      {metric.steps.length > 0 && (
        <>
          <StepBar steps={metric.steps} names={AGENT_STEPS} />
          <StepTable
            steps={metric.steps}
            stt={metric.stt_ttfs}
            names={AGENT_STEPS}
            sttName={AGENT_STT_TTFS}
          />
        </>
      )}
    </section>
  );
}

function missingParts(
  metric: Exclude<AgentReplyTimeMetric, { status: "ok" }>,
  yakshNumber: string | null,
): string {
  switch (metric.status) {
    case "no_traces":
      return `Yaksh found no usable traces when it evaluated this call. It looked for traces with the ID of this call${
        yakshNumber ? ` or with the number ${phone(yakshNumber)}` : ""
      }.`;
    case "not_aligned":
      return "The agent's trace arrived, but Yaksh could not find one clear alignment of the trace with the recording.";
    case "unknown_framework":
      return "The agent's trace arrived, but Yaksh cannot read its framework. Yaksh reads LiveKit Agents 1.8 and Pipecat 1.14.";
    case "clock_off": {
      const lag = Math.round(Math.abs(metric.clock_lag_ms) / 1000);
      return metric.clock_lag_ms > 0
        ? `A trace that matches this call arrived, but its times are about ${lag} s behind Yaksh's clock. The agent's clock is slow, or its spans arrive late. Check NTP on the agent's server.`
        : `A trace that matches this call arrived, but its times are about ${lag} s ahead of Yaksh's clock. The agent's clock is fast. Check NTP on the agent's server.`;
    }
  }
}

/** A part of a reply time, as the metric serves it: in the order the parts happen. */
type Step = { key: string; p50_ms: number; p90_ms: number };
type Percentiles = { replies: number; p50_ms: number; p90_ms: number } | null | undefined;

/** Where a typical reply's time goes: each part's p50, as a share of their sum. */
function StepBar({ steps, names, thin }: { steps: Step[]; names: StepNames; thin?: boolean }) {
  const parts = steps.filter((step) => step.p50_ms > 0);
  if (parts.length === 0) return null;
  return (
    <div
      role="img"
      aria-label={`p50 of each part: ${parts
        .map((step) => `${names.label(step.key)} ${latency(step.p50_ms)}`)
        .join(", ")}`}
      className={cn("flex gap-0.5 overflow-hidden rounded-xs", thin ? "h-2" : "h-3")}
    >
      {parts.map((step) => (
        <span
          key={step.key}
          title={`${names.label(step.key)}: ${latency(step.p50_ms)}`}
          className={STAGE_FILL[names.stage(step.key)]}
          style={{ flex: `${step.p50_ms} 0 0` }}
        />
      ))}
    </div>
  );
}

function StepTable({
  steps,
  stt,
  names,
  sttName,
}: {
  steps: Step[];
  stt: Percentiles;
  names: StepNames;
  sttName: { label: string; tip: string };
}) {
  return (
    <table className="text-s-400 tabular-nums">
      <thead className="text-xs-400 text-muted-foreground">
        <tr>
          <th className="py-1 text-left font-normal">
            <span className="sr-only">Part</span>
          </th>
          <th className="py-1 text-right font-normal">p50</th>
          <th className="py-1 text-right font-normal">p90</th>
        </tr>
      </thead>
      <tbody>
        {steps.map((step) => {
          const tip = names.tip(step.key);
          return (
            <tr key={step.key} className="border-t">
              <td className="py-1.5">
                <span className="flex items-center gap-2">
                  <span className={cn("size-2 rounded-xs", STAGE_FILL[names.stage(step.key)])} />
                  {tip ? (
                    <Explained hint={tip}>{names.label(step.key)}</Explained>
                  ) : (
                    names.label(step.key)
                  )}
                </span>
              </td>
              <td className="py-1.5 text-right">{latency(step.p50_ms)}</td>
              <td className="py-1.5 text-right text-muted-foreground">{latency(step.p90_ms)}</td>
            </tr>
          );
        })}
        {stt && (
          <tr className="border-t border-dashed">
            <td className="py-1.5 pl-4 text-muted-foreground">
              <Explained hint={sttName.tip}>{sttName.label}</Explained>
            </td>
            <td className="py-1.5 text-right text-muted-foreground">{latency(stt.p50_ms)}</td>
            <td className="py-1.5 text-right text-muted-foreground">{latency(stt.p90_ms)}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

/** When the agent's speech stopped after each interruption line: one row for each line, with
 * its words and its time in the transcript; a line with no measure says why. */
function InterruptionsSection({ lines, connectedMs }: { lines: LineRow[]; connectedMs: number }) {
  return (
    <section className="grid gap-3">
      <Heading aside={stoppedSummary(lines)}>
        <Explained hint="When the agent's speech stopped after the caller started each line. A stop from 200ms to 2s counts.">
          Interruptions
        </Explained>
      </Heading>
      <table className="text-s-400 tabular-nums">
        <thead className="text-xs-400 text-muted-foreground">
          <tr>
            <th className="w-10 py-1 text-left font-normal">Line</th>
            <th className="py-1 text-left font-normal">
              <span className="sr-only">Words</span>
            </th>
            <th className="py-1 pr-2 text-right font-normal">At</th>
            <th className="py-1 text-right font-normal">Agent</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.number} className="border-t align-top">
              <td className="py-1.5">{line.number}</td>
              <td className="py-1.5 pr-2 text-muted-foreground">
                “{line.words}”
                {(line.stop.result === "unknown" || line.stop.result === "not_speaking") && (
                  <span className="block text-xs-400">{stopHint(line.stop)}</span>
                )}
              </td>
              <td className="py-1.5 pr-2 text-right">
                {clock(Math.max(0, line.at_ms - connectedMs))}
              </td>
              <td className="py-1 text-right">
                <Badge variant={line.stop.result === "kept_talking" ? "warning" : "tag"}>
                  {stopLabel(line.stop)}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ConversationSection({ metrics }: { metrics: Metrics }) {
  const { turn_taking, speaking } = metrics;
  if (!turn_taking && !speaking) return null;
  const turns = turn_taking?.value;
  return (
    <section className="grid gap-3">
      <Heading>Conversation</Heading>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-3.5 tabular-nums">
        {turns && (
          <>
            <Figure label="Unanswered turns">
              {turns.unanswered} of {turns.expected}
            </Figure>
            <Figure label="Talk-overs">{turns.talked_over}</Figure>
          </>
        )}
        {speaking && (
          <>
            <Figure label="Agent's share of speech">
              {speaking.value.agent_share === null
                ? "No speech"
                : percent(speaking.value.agent_share)}
            </Figure>
            <Figure label="Longest monologue">
              {duration(speaking.value.longest_monologue_ms)}
            </Figure>
          </>
        )}
        {turns?.longest_wait_ms != null &&
          WAIT_LIMITS.map((limit) => (
            <Figure key={limit} label={`Waits of ${limit / 1000}s or more`}>
              {turns.at_least_ms[String(limit)]}
            </Figure>
          ))}
      </dl>
    </section>
  );
}

const WAIT_LIMITS = [3000, 5000, 10000];

function TestRunSection({ metrics, transport }: { metrics: Metrics; transport: Transport }) {
  const usage = metrics.usage?.value;
  const replies = metrics.caller_reply_time?.value;
  // A text call has no ringing, answer or audio times and no bill.
  const timed =
    usage &&
    [usage.ringing_ms, usage.answered_ms, usage.stream_opened_ms, usage.bill_duration_s].some(
      (value) => value != null,
    );
  if (!usage?.settings && !usage?.usage && !replies && !timed) return null;
  return (
    <section className="grid gap-4">
      <Heading>Test run</Heading>
      {(usage?.settings || replies) && (
        <CallerPart settings={usage?.settings ?? null} replies={replies} transport={transport} />
      )}
      {timed && (
        <Subsection title="Call">
          <dl className="grid grid-cols-4 gap-3 tabular-nums">
            <Line label="Ringing at">{since(usage.ringing_ms)}</Line>
            <Line label="Answered at">{since(usage.answered_ms)}</Line>
            <Line label="Audio at">{since(usage.stream_opened_ms)}</Line>
            {usage.bill_duration_s != null && (
              <Line label="Billed by Plivo">{duration(usage.bill_duration_s * 1000)}</Line>
            )}
          </dl>
        </Subsection>
      )}
      {usage?.usage && (
        <Subsection title="Caller usage">
          <CallerUsage consumed={usage.usage} />
        </Subsection>
      )}
    </section>
  );
}

type Usage = NonNullable<Metrics["usage"]>["value"];

function CallerPart({
  settings,
  replies,
  transport,
}: {
  settings: Usage["settings"];
  replies: NonNullable<Metrics["caller_reply_time"]>["value"] | undefined;
  transport: Transport;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="grid gap-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h4 className="text-s-500">Yaksh's caller</h4>
        {replies ? (
          <span className="text-s-400 text-muted-foreground tabular-nums">
            Reply p50 {latency(replies.p50_ms)}, p90 {latency(replies.p90_ms)}
          </span>
        ) : (
          transport === "phone" && (
            <span className="text-s-400 text-muted-foreground">Reply time not measured</span>
          )
        )}
      </div>
      {settings && (
        <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-s-400">
          <Setting label="LLM">
            {settings.llm_model}
            {settings.reasoning_effort && `, ${settings.reasoning_effort} effort`}
            {settings.scenario_model && " (set by the scenario)"}
          </Setting>
          {settings.stt_model && (
            <Setting label="STT">
              {settings.stt_provider && `${sttProvider(settings.stt_provider).label} `}
              {settings.stt_model}
              {settings.stt_language && `, ${settings.stt_language}`}
            </Setting>
          )}
          {settings.voice && (
            <Setting label="TTS">
              {ttsProvider(settings.voice.provider).label}
              {settings.tts_model && ` ${settings.tts_model}`}
            </Setting>
          )}
          {settings.vad_stop_s != null && (
            <Setting label="VAD stop">{settings.vad_stop_s}s</Setting>
          )}
          {settings.turn_max_wait_s != null && (
            <Setting label="Turn wait">Up to {settings.turn_max_wait_s}s</Setting>
          )}
        </dl>
      )}
      {replies && replies.steps.length > 0 && (
        <>
          <StepBar steps={replies.steps} names={CALLER_STEPS} thin />
          <Button
            type="button"
            variant="outline"
            size="xs"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="justify-self-start"
          >
            {open ? "Hide the caller's parts" : "Show the caller's parts"}
          </Button>
          {open && (
            <StepTable
              steps={replies.steps}
              stt={replies.stt_ttfs}
              names={CALLER_STEPS}
              sttName={STT_TTFS}
            />
          )}
        </>
      )}
    </div>
  );
}

function CallerUsage({ consumed }: { consumed: NonNullable<Usage["usage"]> }) {
  const figures = [
    consumed.llm_prompt_tokens != null && (
      <Line key="prompt" label="Prompt tokens">
        {count(consumed.llm_prompt_tokens)}
        {consumed.llm_cache_read_tokens != null && (
          <span className="text-muted-foreground">
            {" "}
            ({count(consumed.llm_cache_read_tokens)} cached)
          </span>
        )}
      </Line>
    ),
    consumed.llm_completion_tokens != null && (
      <Line key="output" label="Output tokens">
        {count(consumed.llm_completion_tokens)}
        {consumed.llm_reasoning_tokens != null && (
          <span className="text-muted-foreground">
            {" "}
            ({count(consumed.llm_reasoning_tokens)} reasoning)
          </span>
        )}
      </Line>
    ),
    consumed.tts_characters != null && (
      <Line key="spoken" label="Spoken">
        {counted(consumed.tts_characters, "character", "characters")}
      </Line>
    ),
    consumed.stt_audio_seconds != null && (
      <Line key="transcribed" label="Transcribed">
        {duration(consumed.stt_audio_seconds * 1000)} of audio
      </Line>
    ),
  ].filter(Boolean);
  if (figures.length === 0) {
    return <p className="text-s-400 text-muted-foreground">No usage reported</p>;
  }
  return <dl className="grid grid-cols-2 gap-x-3 gap-y-2.5 tabular-nums">{figures}</dl>;
}

function Subsection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-t pt-3.5">
      <h4 className="text-s-500">{title}</h4>
      {children}
    </div>
  );
}

/** A time from the start of the conversation, or a dash when it did not happen. */
function since(ms: number | null | undefined): string {
  return ms == null ? "–" : seconds(ms);
}

function count(value: number): string {
  return value.toLocaleString("en-US");
}

function Figure({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="text-h4-500">{children}</dd>
    </div>
  );
}

function Setting({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="wrap-anywhere">{children}</dd>
    </>
  );
}

function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="text-s-400 wrap-anywhere">{children}</dd>
    </div>
  );
}
