import { Copy } from "lucide-react";
import { copyText } from "@/lib/clipboard";

/** A record's id, shortened to its random tail since UUIDv7 ids share their time prefix;
 * the button copies the full id for API calls. */
export function CopyId({ id, label }: { id: string; label: string }) {
  return (
    <button
      type="button"
      title={id}
      aria-label={`Copy ${label}`}
      onClick={() => void copyText(id, `${label[0].toUpperCase()}${label.slice(1)} copied`)}
      className="relative z-10 inline-flex items-center gap-1.5 rounded-sm font-mono text-xs text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      {id.slice(-8)}
      <Copy className="size-3.5" />
    </button>
  );
}
