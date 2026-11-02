import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { BAND_TAG, latency, responseBand } from "@/lib/format";
import { AGENT_STEPS, AGENT_STT_TTFS, agentInOrder, STAGE_FILL } from "@/lib/reply-steps";
import type { AgentReplyTime } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How long the agent made the caller wait, in the colour of its band, as ResponseTime shows it.
 * Hovering or focusing it lists where the time went, from the agent's trace. */
export function AgentResponseTime({ ms, reply }: { ms: number; reply: AgentReplyTime }) {
  const steps = agentInOrder(Object.entries(reply.steps ?? {}));
  const parts = steps.filter(([, part]) => part > 0);
  const vad = steps.find(([key]) => AGENT_STEPS.stage(key) === "turn")?.[0];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            className={cn(
              "rounded-sm px-1.5 text-xs-500 leading-5 tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              BAND_TAG[responseBand(ms)],
            )}
          />
        }
      >
        {latency(ms)}
      </TooltipTrigger>
      <TooltipContent side="bottom" className="grid min-w-56 gap-1 py-2">
        <span className="text-xs-500">Agent response {latency(ms)}</span>
        {parts.map(([key, part]) => (
          <span key={key} className="flex items-center justify-between gap-4 tabular-nums">
            <span className="flex items-center gap-1.5">
              <span className={cn("size-2 rounded-xs", STAGE_FILL[AGENT_STEPS.stage(key)])} />
              {AGENT_STEPS.label(key)}
            </span>
            {latency(part)}
          </span>
        ))}
        {reply.stt_ttfs_ms != null && (
          <span className="flex items-center justify-between gap-4 border-t border-background/20 pt-1 tabular-nums">
            <span>
              {AGENT_STT_TTFS.label}
              {vad && ` (overlaps ${AGENT_STEPS.label(vad)})`}
            </span>
            <span>{latency(reply.stt_ttfs_ms)}</span>
          </span>
        )}
        {reply.agent_ms != null && (
          <span className="flex items-center justify-between gap-4 tabular-nums">
            Agent's total
            <span>{latency(reply.agent_ms)}</span>
          </span>
        )}
      </TooltipContent>
    </Tooltip>
  );
}
