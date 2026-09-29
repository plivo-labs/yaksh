import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { exact, since } from "@/lib/format";

/** "3 minutes ago", with the exact time on hover. It sits above a row's full-width link so the
 * hover reaches it. */
export function RelativeTime({ iso }: { iso: string }) {
  return (
    <Tooltip>
      <TooltipTrigger render={<time dateTime={iso} className="relative z-10 cursor-default" />}>
        {since(iso)}
      </TooltipTrigger>
      <TooltipContent>{exact(iso)}</TooltipContent>
    </Tooltip>
  );
}
