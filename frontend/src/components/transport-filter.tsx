import { FilterSelect } from "@/components/filter-select";
import { cn } from "@/lib/utils";
import type { Transport } from "@/lib/types";

const ANY = "any";
const ITEMS = [
  { value: ANY, label: "All connections" },
  { value: "phone", label: "Phone" },
  { value: "text", label: "Text" },
];

/** Narrows a run list to the runs of one connection: phone or text. */
export function TransportFilter({
  transport,
  onTransportChange,
  className,
}: {
  transport: Transport | undefined;
  onTransportChange: (transport: Transport | undefined) => void;
  className?: string;
}) {
  return (
    <FilterSelect
      label="Filter by connection"
      items={ITEMS}
      value={transport ?? ANY}
      onChange={(value) =>
        onTransportChange(value === "phone" || value === "text" ? value : undefined)
      }
      className={cn("w-36", className)}
    />
  );
}
