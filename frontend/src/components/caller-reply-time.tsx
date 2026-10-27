import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { latency } from "@/lib/format";
import { inOrder, SHOWN_PART_MS, STAGE_FILL, stepLabel, stepStage } from "@/lib/reply-steps";
import type { CallerReplyTime } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How long the caller took to reply, in a neutral tag: the agent's response times keep the
 * color. Hovering or focusing it lists the reply's parts. */
export function CallerReplyBadge({ reply }: { reply: CallerReplyTime }) {
  const parts = inOrder(Object.entries(reply.steps)).filter(([, ms]) => ms >= SHOWN_PART_MS);
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            className="rounded-sm bg-muted px-1.5 text-xs-500 leading-5 text-muted-foreground tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          />
        }
      >
        {latency(reply.total_ms)}
      </TooltipTrigger>
      <TooltipContent side="bottom" className="grid min-w-52 gap-1 py-2">
        <span className="text-xs-500">Caller reply {latency(reply.total_ms)}</span>
        {parts.map(([key, ms]) => (
          <span key={key} className="flex items-center justify-between gap-4 tabular-nums">
            <span className="flex items-center gap-1.5">
              <span className={cn("size-2 rounded-xs", STAGE_FILL[stepStage(key)])} />
              {stepLabel(key)}
            </span>
            {latency(ms)}
          </span>
        ))}
      </TooltipContent>
    </Tooltip>
  );
}
