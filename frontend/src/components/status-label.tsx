import type { ReactNode } from "react";

import { Settle } from "@/components/settle";
import { upperFirst, words } from "@/lib/format";
import { CONVERSATION_TONE, RESULT_TONE, RUN_TONE, type Tone } from "@/lib/status";
import type { ConversationStatus, RunResult, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLOR: Record<Tone, string> = {
  amber: "bg-status-warning",
  green: "bg-status-success",
  red: "bg-status-danger",
  off: "bg-status-neutral",
};

/** The dot carries the color; the word stays ink, or muted while the status is waiting or over. */
const TEXT: Record<Tone, string> = {
  amber: "text-muted-foreground",
  green: "text-foreground",
  red: "text-foreground",
  off: "text-muted-foreground",
};

/** A flat status dot. A live one pulses gently. */
function Dot({
  tone,
  live = false,
  size = "md",
  className,
}: {
  tone: Tone;
  live?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block shrink-0 rounded-full",
        COLOR[tone],
        size === "sm" && "size-1.5",
        size === "md" && "size-2",
        size === "lg" && "size-2.5",
        live && "motion-safe:animate-[breathe_1.6s_ease-in-out_infinite]",
        className,
      )}
    />
  );
}

/** A status as an 8px dot and a word, without a chip. */
export function StatusLabel({
  tone,
  live = false,
  children,
}: {
  tone: Tone;
  live?: boolean;
  children: ReactNode;
}) {
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-s-400 whitespace-nowrap", TEXT[tone])}
    >
      <Dot tone={tone} live={live} />
      {children}
    </span>
  );
}

export function ConversationStatusLabel({ status }: { status: ConversationStatus }) {
  return (
    <Settle value={status}>
      <StatusLabel tone={CONVERSATION_TONE[status]} live={status === "running"}>
        {upperFirst(words(status))}
      </StatusLabel>
    </Settle>
  );
}

/** The result of a run against a suite's pass rate, or of a suite run. */
export function ResultLabel({ result }: { result: RunResult }) {
  return (
    <Settle value={result}>
      <StatusLabel tone={RESULT_TONE[result]} live={result === "running"}>
        {upperFirst(words(result))}
      </StatusLabel>
    </Settle>
  );
}

export function RunStatusLabel({ status }: { status: RunStatus }) {
  return (
    <Settle value={status}>
      <StatusLabel tone={RUN_TONE[status]} live={status === "running"}>
        {upperFirst(status)}
      </StatusLabel>
    </Settle>
  );
}
