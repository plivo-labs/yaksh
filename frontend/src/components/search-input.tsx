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
  /** The last search this box sent. The address reports it back later, after newer typing. */
  const sent = useRef(value);
  // A search set elsewhere, such as by the sidebar link, replaces the typed text and the search
  // still waiting.
  useEffect(() => {
    if (value === sent.current) return;
    sent.current = value;
    clearTimeout(timer.current);
    setTyped(value);
  }, [value]);
  // A search still waiting when the page closes would change the next page's address.
  useEffect(() => () => clearTimeout(timer.current), []);
  const type = (text: string) => {
    setTyped(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      sent.current = text.trim();
      onSearch(sent.current);
    }, SEARCH_DELAY_MS);
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
