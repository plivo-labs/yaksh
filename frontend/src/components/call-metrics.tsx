import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { duration, percent, seconds } from "@/lib/format";
import { useConversationEvaluation } from "@/lib/queries";
import {
  type CaptureFaults,
  type ConversationEvaluation,
  type EvaluationState,
  FLAG_TEXT,
  evaluationPending,
} from "@/lib/types";

/** What the evaluator computed for the call, once it is done. */
export function CallMetricsCard({
  conversationId,
  evaluation,
}: {
  conversationId: string;
  evaluation: EvaluationState | null;
}) {
  const found = useConversationEvaluation(conversationId, evaluation);
  if (evaluation === null) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Call metrics</CardTitle>
        {evaluationPending(evaluation) && <CardDescription>Measuring the call.</CardDescription>}
        {evaluation === "failed" && (
          <CardDescription className="text-status-danger wrap-anywhere">
            The measurement failed{found.data?.failure ? `: ${found.data.failure}` : "."}
          </CardDescription>
        )}
        {found.isError && (
          <CardDescription role="alert" className="text-status-danger">
            Could not load the metrics: {found.error.message}
          </CardDescription>
        )}
      </CardHeader>
      {evaluation === "done" && found.data && <Metrics found={found.data} />}
    </Card>
  );
}

function Metrics({ found }: { found: ConversationEvaluation }) {
  const { turn_taking, speaking, agent_repetition, capture_faults, usage } = found.metrics;
  const flags = [...new Set(Object.values(found.metrics).flatMap((metric) => metric.flags))];
  const consumed = usage?.value.usage;
  const settings = usage?.value.settings;
  return (
    <CardContent className="grid gap-3 text-p-400">
      {flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {flags.map((flag) => (
            <Badge key={flag} variant="tag">
              {FLAG_TEXT[flag] ?? flag}
            </Badge>
          ))}
        </div>
      )}
      <dl className="grid gap-3">
        {turn_taking && (
          <Line label="Turns that expected an answer">
            {turn_taking.value.expected}, {turn_taking.value.unanswered} unanswered,{" "}
            {turn_taking.value.talked_over} where the agent spoke over the caller
          </Line>
        )}
        {turn_taking?.value.longest_wait_ms != null && (
          <Line label="Longest wait">
            {seconds(turn_taking.value.longest_wait_ms)}; waits of 3s, 5s and 10s or more:{" "}
            {["3000", "5000", "10000"]
              .map((limit) => turn_taking.value.at_least_ms[limit])
              .join(", ")}
          </Line>
        )}
        {speaking && (
          <Line label="Agent's share of the speech">
            {speaking.value.agent_share === null
              ? "No speech"
              : percent(speaking.value.agent_share)}
            , longest monologue {duration(speaking.value.longest_monologue_ms)}
          </Line>
        )}
        {agent_repetition?.value.runs.map((run) => (
          <Line key={run.at_ms} label={`Said ${run.count} times in a row`}>
            {run.text}
          </Line>
        ))}
        {capture_faults && capture_faults.flags.length > 0 && (
          <Line label="Record problems">{problems(capture_faults.value)}</Line>
        )}
        {settings && (
          <Line label="Caller models">
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
          </Line>
        )}
        {consumed && (
          <Line label="Caller usage">
            {[
              consumed.llm_prompt_tokens !== null && `${consumed.llm_prompt_tokens} prompt tokens`,
              consumed.llm_completion_tokens !== null &&
                `${consumed.llm_completion_tokens} output tokens`,
              consumed.tts_characters !== null && `${consumed.tts_characters} characters spoken`,
              consumed.stt_audio_seconds !== null &&
                `${Math.round(consumed.stt_audio_seconds)}s of audio transcribed`,
            ]
              .filter(Boolean)
              .join(", ") || "None reported"}
          </Line>
        )}
        {usage && (
          <Line label="Connection, from the start of the call">
            {[
              usage.value.ringing_ms !== null && `ringing at ${seconds(usage.value.ringing_ms)}`,
              usage.value.answered_ms !== null && `answered at ${seconds(usage.value.answered_ms)}`,
              usage.value.stream_opened_ms !== null &&
                `audio at ${seconds(usage.value.stream_opened_ms)}`,
            ]
              .filter(Boolean)
              .join(", ") || "Not connected"}
          </Line>
        )}
        {usage?.value.bill_duration_s != null && (
          <Line label="Billed by Plivo">{usage.value.bill_duration_s}s</Line>
        )}
      </dl>
    </CardContent>
  );
}

/** The record's problems as counts. The flags above name them; these say how many. */
function problems(faults: CaptureFaults): string {
  if ("incomplete_record" in faults) {
    return "The worker stopped before it saved the call in full.";
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

function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="wrap-anywhere">{children}</dd>
    </div>
  );
}
