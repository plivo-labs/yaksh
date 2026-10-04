import { BAND_FILL, BAND_TEXT, responseBand, seconds } from "@/lib/format";
import { cn } from "@/lib/utils";

/** How long the agent made the caller wait, in the colour of its band. */
export function ResponseTime({ ms, className }: { ms: number; className?: string }) {
  const band = responseBand(ms);
  return (
    <span
      className={cn(
        "rounded-sm px-1.5 font-mono text-xs leading-5 tabular-nums",
        BAND_FILL[band],
        BAND_TEXT[band],
        className,
      )}
    >
      {seconds(ms)}
    </span>
  );
}
