import { Check } from "lucide-react";
import { Link } from "react-router";

import { cn } from "@/lib/utils";

export interface Step {
  label: string;
  hint: string;
}

/** A wizard's steps in order. A finished step's name links back to it. */
export function Steps({
  steps,
  current,
  href,
  locked = false,
}: {
  steps: Step[];
  current: number;
  href: (step: number) => string;
  /** No step links while the steps cannot change. */
  locked?: boolean;
}) {
  return (
    <ol aria-label="Steps" className="grid gap-3 sm:auto-cols-fr sm:grid-flow-col">
      {steps.map((step, index) => {
        const number = index + 1;
        const done = number < current;
        const now = number === current;
        const text = (
          <span className="grid">
            <span className={cn("text-p-500", !done && !now && "text-muted-foreground")}>
              {step.label}
              {done && <span className="sr-only"> (done)</span>}
            </span>
            <span className="text-xs-400 text-muted-foreground">{step.hint}</span>
          </span>
        );
        return (
          <li
            key={step.label}
            aria-current={now ? "step" : undefined}
            className={cn(
              "flex items-center gap-2.5 border-t-2 pt-3",
              done || now ? "border-foreground" : "border-border",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full text-xs-500 tabular-nums",
                done && "bg-primary text-primary-foreground",
                now && "ring-[1.5px] ring-foreground ring-inset",
                !done && !now && "bg-muted text-muted-foreground",
              )}
            >
              {done ? <Check className="size-3" /> : number}
            </span>
            {done && !locked ? (
              <Link
                to={href(number)}
                className="rounded-sm outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                {text}
              </Link>
            ) : (
              text
            )}
          </li>
        );
      })}
    </ol>
  );
}
