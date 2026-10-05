import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

/** A column heading that sorts a list. `sort` is the current key, `-` first for descending;
 * the first click on a date or duration sorts descending, on text ascending. */
export function SortHeader({
  label,
  field,
  sort,
  descendingFirst = false,
  onSort,
}: {
  label: string;
  field: string;
  sort: string;
  descendingFirst?: boolean;
  onSort: (sort: string) => void;
}) {
  const descending = sort === `-${field}`;
  const active = descending || sort === field;
  const first = descendingFirst ? `-${field}` : field;
  const next = active ? (descending ? field : `-${field}`) : first;
  const Icon = active ? (descending ? ArrowDown : ArrowUp) : ArrowUpDown;
  return (
    <button
      type="button"
      onClick={() => onSort(next)}
      aria-label={`Sort by ${label.toLowerCase()}`}
      aria-pressed={active}
      className={`-mx-1 inline-flex w-fit items-center gap-1 rounded-sm px-1 whitespace-nowrap outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 ${active ? "text-foreground" : ""}`}
    >
      {label}
      <Icon className={`size-3.5 ${active ? "" : "opacity-50"}`} />
    </button>
  );
}
