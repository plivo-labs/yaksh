import { cn } from "cn";

import { Badge } from "@/components/ui/badge";
import { words } from "@/lib/format";
import type { ConversationStatus } from "@/lib/types";

const DOT: Record<ConversationStatus, string> = {
  queued: "bg-status-neutral",
  running: "bg-status-progress",
  ending: "bg-status-warning",
  completed: "bg-status-success",
  failed: "bg-status-danger",
  invalid: "bg-status-warning",
  cancelled: "bg-status-neutral",
};

export function StatusBadge({ status }: { status: ConversationStatus }) {
  return (
    <Badge variant="secondary" className="gap-1.5 capitalize">
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          DOT[status],
          status === "running" && "animate-pulse",
        )}
      />
      {words(status)}
    </Badge>
  );
}
