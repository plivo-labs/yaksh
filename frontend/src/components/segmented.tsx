import type { KeyboardEvent } from "react";

/** A row of mutually exclusive options, all visible at once. Arrow keys move the choice, as in
 * any radio group. The segments share one width so a single thumb can slide between them. */
export function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
  disabled = false,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  disabled?: boolean;
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
      <span className="text-s-500">{label}</span>
      <div
        role="radiogroup"
        aria-label={label}
        aria-disabled={disabled || undefined}
        onKeyDown={key}
        className="relative grid w-fit auto-cols-fr grid-flow-col rounded-md border bg-muted p-[3px] aria-disabled:opacity-50"
      >
        {index >= 0 && (
          <span
            aria-hidden
            className="absolute inset-y-[3px] left-[3px] rounded-md border border-border bg-card shadow-sm transition-transform duration-200 ease-out motion-reduce:transition-none"
            style={{
              width: `calc((100% - 6px) / ${options.length})`,
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
              disabled={disabled}
              data-value={option.value}
              onClick={() => onChange(option.value)}
              className={`relative rounded-md px-4 py-1.5 text-s-500 whitespace-nowrap tabular-nums outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed ${checked ? "text-foreground" : "text-muted-foreground not-disabled:hover:text-secondary"}`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
