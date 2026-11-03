import { useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { stopHint, stopLabel } from "@/lib/stops";
import type { LineStop } from "@/lib/types";

/** When the agent's speech stopped after an interruption line, as a tag whose tooltip says it
 * in a sentence; the sentence opens on hover and on focus, and a screen reader reads it. */
export function LineStopBadge({ stop }: { stop: LineStop }) {
  const id = useId();
  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <Badge
              tabIndex={0}
              aria-describedby={id}
              variant={stop.result === "kept_talking" ? "warning" : "tag"}
              className="cursor-help outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            />
          }
        >
          {stopLabel(stop)}
        </TooltipTrigger>
        <TooltipContent className="max-w-72">{stopHint(stop)}</TooltipContent>
      </Tooltip>
      <span id={id} className="sr-only">
        {stopHint(stop)}
      </span>
    </>
  );
}
