import { cn } from "cn";
import type { ComponentProps, ReactNode } from "react";

/** A framed section of a page. */
export function Panel({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn(
        "rounded-lg border bg-card shadow-[inset_0_1px_0_rgb(255_255_255/0.55),0_1px_2px_rgb(0_0_0/0.05)] dark:shadow-[inset_0_1px_0_rgb(255_255_255/0.03)]",
        className,
      )}
      {...props}
    />
  );
}

export function PanelHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b px-5 py-3.5">
      <h2 className="text-[15px] font-semibold tracking-[-0.005em]">{title}</h2>
      {action}
    </header>
  );
}

/** One labelled fact in a row of fixed furniture. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate text-sm font-medium">{children}</dd>
    </div>
  );
}
