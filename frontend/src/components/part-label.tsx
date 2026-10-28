import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** A part's name with what it measures on hover or focus; just the name when there is no tip. */
export function PartLabel({ tip, children }: { tip: string; children: ReactNode }) {
  if (!tip) return <>{children}</>;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            tabIndex={0}
            className="cursor-help rounded-xs underline decoration-dotted decoration-muted-foreground underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-64">
        {tip}
      </TooltipContent>
    </Tooltip>
  );
}
