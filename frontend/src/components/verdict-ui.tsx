import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleMinus,
  CircleSlash,
  CircleX,
  type LucideIcon,
} from "lucide-react";
import { type ReactNode, useId } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { OUTCOME_TEXT, type Outcome, VERDICT_TEXT, type Verdict } from "@/lib/types";
import { cn } from "@/lib/utils";

const OUTCOME_ICON: Record<Outcome, { icon: LucideIcon; color: string }> = {
  pass: { icon: CircleCheck, color: "text-status-success" },
  fail: { icon: CircleX, color: "text-status-danger" },
  not_applicable: { icon: CircleMinus, color: "text-muted-foreground/70" },
  unsure: { icon: CircleHelp, color: "text-status-warning" },
  blocked: { icon: CircleSlash, color: "text-status-warning" },
  error: { icon: CircleAlert, color: "text-status-danger" },
  pending: { icon: CircleDashed, color: "text-status-warning" },
};

/** An item's outcome as an icon. Screen readers read its name, unless it is `decorative`:
 * set that where the outcome's name is already written next to it. */
export function OutcomeIcon({
  outcome,
  className,
  decorative = false,
}: {
  outcome: Outcome;
  className?: string;
  decorative?: boolean;
}) {
  const { icon: Icon, color } = OUTCOME_ICON[outcome];
  const name = decorative
    ? { "aria-hidden": true }
    : { role: "img", "aria-label": OUTCOME_TEXT[outcome] };
  return <Icon {...name} className={cn("size-4 shrink-0", color, className)} />;
}

const PILL: Record<Verdict, string> = {
  pass: "bg-status-success/12 text-status-success-text",
  fail: "bg-status-danger/10 text-status-danger-text",
  not_scored: "bg-status-warning/12 text-status-warning-text",
};

/** A verdict as a filled pill: the one thing to see first. */
export function VerdictPill({ verdict }: { verdict: Verdict }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-s-500 font-medium whitespace-nowrap",
        PILL[verdict],
      )}
    >
      {VERDICT_TEXT[verdict]}
    </span>
  );
}

/** A label with a dotted underline that explains itself on hover or focus. The tooltip sets no
 * description, so a hidden copy of the hint gives screen readers the same text. */
export function Explained({
  children,
  hint,
  className,
}: {
  children: ReactNode;
  hint: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <>
      <Tooltip>
        <TooltipTrigger
          aria-describedby={id}
          className={cn(
            "cursor-help rounded-sm text-left underline decoration-muted-foreground/40 decoration-dotted underline-offset-[3px] outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
            className,
          )}
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

const TONE_FILL = {
  good: "bg-status-success",
  bad: "bg-status-danger",
  warn: "bg-status-warning",
  neutral: "bg-foreground/70",
} as const;

/** A 0 to 100% bar. With a range, the bar shows the range as a tinted band and the value as a
 * mark inside it, so an estimate reads as one; without, the value is a plain fill. */
export function Meter({
  value,
  low,
  high,
  tone = "neutral",
  label,
}: {
  value: number;
  low?: number | null;
  high?: number | null;
  tone?: keyof typeof TONE_FILL;
  label: string;
}) {
  const ranged = low != null && high != null;
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
      className={cn(
        "relative w-full rounded-full bg-muted",
        ranged ? "h-2" : "h-1.5 overflow-hidden",
      )}
    >
      {ranged ? (
        <>
          <span
            aria-hidden
            className={cn("absolute inset-y-0 rounded-full opacity-35", TONE_FILL[tone])}
            style={{ left: `${low * 100}%`, width: `${Math.max(0.01, high - low) * 100}%` }}
          />
          <span
            aria-hidden
            className={cn(
              "absolute -inset-y-0.5 w-[3px] -translate-x-1/2 rounded-full",
              TONE_FILL[tone],
            )}
            style={{ left: `${value * 100}%` }}
          />
        </>
      ) : (
        <span
          aria-hidden
          className={cn("absolute inset-y-0 left-0 rounded-full", TONE_FILL[tone])}
          style={{ width: `${value * 100}%` }}
        />
      )}
    </div>
  );
}

const SEGMENT: Record<string, string> = {
  pass: "bg-status-success",
  fail: "bg-status-danger",
  error: "bg-status-danger/60",
  blocked: "bg-status-warning",
  unsure: "bg-status-warning/50",
  pending: "bg-status-warning/50",
  not_applicable: "bg-muted-foreground/30",
  not_testable: "bg-muted-foreground/30",
};

const SEGMENT_ORDER = [
  "pass",
  "fail",
  "error",
  "blocked",
  "unsure",
  "pending",
  "not_testable",
  "not_applicable",
];

/** Outcome counts as one stacked bar, in a fixed order so bars compare row to row. */
export function SegmentBar({ counts, label }: { counts: Record<string, number>; label: string }) {
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
  if (total === 0) return null;
  return (
    <div
      role="img"
      aria-label={label}
      className="flex h-1.5 w-full gap-px overflow-hidden rounded-full"
    >
      {SEGMENT_ORDER.filter((key) => counts[key]).map((key) => (
        <span
          key={key}
          className={cn("h-full first:rounded-l-full last:rounded-r-full", SEGMENT[key])}
          style={{ width: `${(counts[key] / total) * 100}%` }}
        />
      ))}
    </div>
  );
}

/** A big number and what it means: the glance layer of a panel. */
export function Stat({
  label,
  hint,
  value,
  children,
}: {
  label: string;
  hint: ReactNode;
  value: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="grid content-start gap-2 rounded-lg border bg-card px-4 py-3.5">
      <Explained hint={hint} className="justify-self-start text-label text-muted-foreground">
        {label}
      </Explained>
      <div className="font-heading text-[26px] leading-[30px] font-medium tracking-[-0.02em] tabular-nums">
        {value}
      </div>
      {children}
    </div>
  );
}
