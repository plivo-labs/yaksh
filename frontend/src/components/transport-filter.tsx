import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
    <Select
      items={ITEMS}
      value={transport ?? ANY}
      onValueChange={(value) =>
        onTransportChange(value === "phone" || value === "text" ? value : undefined)
      }
    >
      <SelectTrigger size="sm" className={cn("w-36", className)} aria-label="Filter by connection">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {ITEMS.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
