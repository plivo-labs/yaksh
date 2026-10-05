import { BAND_TAG, responseBand, seconds } from "@/lib/format";
import { cn } from "@/lib/utils";

/** How long the agent made the caller wait, in the colour of its band. */
export function ResponseTime({ ms, className }: { ms: number; className?: string }) {
  const band = responseBand(ms);
  return (
    <span
      className={cn(
        "rounded-sm px-1.5 text-xs-500 leading-5 tabular-nums",
        BAND_TAG[band],
        className,
      )}
    >
      {seconds(ms)}
    </span>
  );
}
