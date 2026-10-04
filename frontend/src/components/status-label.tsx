import type { ReactNode } from "react";

import { Settle } from "@/components/settle";
import { words } from "@/lib/format";
import { CONVERSATION_TONE, RUN_TONE, type Tone } from "@/lib/status";
import type { ConversationStatus, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLOR: Record<Tone, string> = {
  amber: "bg-status-warning",
  green: "bg-status-success",
  red: "bg-status-danger",
  off: "bg-status-idle",
};

/** The CX console's status text: only a failure is colored, the dot carries the rest. */
const TEXT: Record<Tone, string> = {
  amber: "text-muted-foreground",
  green: "text-foreground",
  red: "text-status-danger",
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

/** A status as the CX console shows it: a dot and mono text, without a chip. */
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
      className={cn(
        "inline-flex items-center gap-1.5 font-mono text-xs-400 whitespace-nowrap capitalize",
        TEXT[tone],
      )}
    >
      <Dot tone={tone} live={live} size="sm" />
      {children}
    </span>
  );
}

export function ConversationStatusLabel({ status }: { status: ConversationStatus }) {
  return (
    <Settle value={status}>
      <StatusLabel tone={CONVERSATION_TONE[status]} live={status === "running"}>
        {words(status)}
      </StatusLabel>
    </Settle>
  );
}

export function RunStatusLabel({ status }: { status: RunStatus }) {
  return (
    <Settle value={status}>
      <StatusLabel tone={RUN_TONE[status]} live={status === "running"}>
        {status}
      </StatusLabel>
    </Settle>
  );
}
