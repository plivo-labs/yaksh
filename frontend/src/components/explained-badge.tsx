import { type ComponentProps, type ReactNode, useId } from "react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** A tag that explains itself on hover or focus, as `Explained` does for a label. The tooltip
 * sets no description, so a hidden copy of the hint gives screen readers the same text. */
export function ExplainedBadge({
  hint,
  variant,
  className,
  children,
}: {
  hint: string;
  variant?: ComponentProps<typeof Badge>["variant"];
  className?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <Badge
              variant={variant}
              tabIndex={0}
              aria-describedby={id}
              className={cn("cursor-help outline-none", className)}
            />
          }
        >
          {children}
        </TooltipTrigger>
        <TooltipContent className="max-w-72">{hint}</TooltipContent>
      </Tooltip>
      <span id={id} className="sr-only">
        {hint}
      </span>
    </>
  );
}
