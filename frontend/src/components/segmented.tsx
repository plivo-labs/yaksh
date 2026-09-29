import type { KeyboardEvent } from "react";

/** A row of mutually exclusive options, all visible at once. Arrow keys move the choice, as in
 * any radio group. The segments share one width so a single thumb can slide between them. */
export function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const index = options.findIndex((option) => option.value === value);
  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const step =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (!step) return;
    event.preventDefault();
    const next = options[(index + step + options.length) % options.length];
    onChange(next.value);
    event.currentTarget.querySelector<HTMLButtonElement>(`[data-value="${next.value}"]`)?.focus();
  };
  return (
    <div className="grid gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div
        role="radiogroup"
        aria-label={label}
        onKeyDown={key}
        className="relative grid w-fit auto-cols-fr grid-flow-col rounded-md bg-muted p-0.5"
      >
        {index >= 0 && (
          <span
            aria-hidden
            className="absolute inset-y-0.5 left-0.5 rounded-[5px] bg-background shadow-sm transition-transform duration-200 ease-out motion-reduce:transition-none"
            style={{
              width: `calc((100% - 0.25rem) / ${options.length})`,
              transform: `translateX(${index * 100}%)`,
            }}
          />
        )}
        {options.map((option) => {
          const checked = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={checked ? 0 : -1}
              data-value={option.value}
              onClick={() => onChange(option.value)}
              className={`relative rounded-[5px] px-2.5 py-1 text-sm whitespace-nowrap tabular-nums outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring/50 ${checked ? "text-foreground" : "text-muted-foreground hover:text-foreground"}`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
