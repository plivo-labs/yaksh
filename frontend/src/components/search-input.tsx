import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";

const SEARCH_DELAY_MS = 250;

/** A search box that reports its text once typing pauses, so each pause makes one request. */
export function SearchInput({
  value,
  onSearch,
  label,
  placeholder,
  className,
}: {
  value: string;
  onSearch: (text: string) => void;
  label: string;
  placeholder: string;
  className?: string;
}) {
  const [typed, setTyped] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // A search still waiting when the page closes would change the next page's address.
  useEffect(() => () => clearTimeout(timer.current), []);
  const type = (text: string) => {
    setTyped(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => onSearch(text.trim()), SEARCH_DELAY_MS);
  };
  return (
    <div className={`relative ${className ?? ""}`}>
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        aria-label={label}
        placeholder={placeholder}
        className="h-[30px] pl-8 text-s-400"
        value={typed}
        onChange={(event) => type(event.target.value)}
      />
    </div>
  );
}
