import { cn } from "cn";

import { Settle } from "@/components/settle";
import { Badge } from "@/components/ui/badge";
import { words } from "@/lib/format";
import type { ConversationStatus, RunStatus } from "@/lib/types";

type Tone = "amber" | "green" | "red" | "off";

const COLOR: Record<Tone, string> = {
  amber: "bg-status-warning",
  green: "bg-status-success",
  red: "bg-status-danger",
  off: "bg-status-idle",
};

const TONE: Record<ConversationStatus, Tone> = {
  queued: "amber",
  running: "green",
  ending: "amber",
  completed: "green",
  failed: "red",
  invalid: "red",
  cancelled: "off",
};

/** A flat status dot. A live one pulses gently. */
export function Dot({
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

export function StatusDot({
  status,
  size,
  className,
}: {
  status: ConversationStatus;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return <Dot tone={TONE[status]} live={status === "running"} size={size} className={className} />;
}

export function StatusBadge({ status }: { status: ConversationStatus }) {
  return (
    <Settle value={status}>
      <Badge variant="outline" className="gap-1.5 capitalize">
        <StatusDot status={status} size="sm" />
        {words(status)}
      </Badge>
    </Settle>
  );
}

const RUN_TONE: Record<RunStatus, Tone> = {
  queued: "amber",
  running: "green",
  cancelling: "amber",
  done: "green",
  cancelled: "off",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Settle value={status}>
      <Badge variant="outline" className="gap-1.5 capitalize">
        <Dot tone={RUN_TONE[status]} live={status === "running"} size="sm" />
        {status}
      </Badge>
    </Settle>
  );
}
