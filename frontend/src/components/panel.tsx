import type { ComponentProps, ReactNode } from "react";

import { REVEAL } from "@/lib/motion";
import { cn } from "@/lib/utils";

/** A framed section of a page. */
export function Panel({ className, ...props }: ComponentProps<"section">) {
  return <section className={cn("rounded-lg border bg-card", className)} {...props} />;
}

export function PanelHeader({ title, action }: { title: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b px-5 py-3.5">
      <h2 className="text-h4-500">{title}</h2>
      {action}
    </header>
  );
}

/** A panel with its actions above its content and `notice` between the two. Inside a tab the tab
 * names the panel, so it has no `title`. */
export function ActionPanel({
  title,
  action,
  notice,
  className,
  children,
  ...props
}: Omit<ComponentProps<"section">, "title"> & {
  title?: ReactNode;
  action?: ReactNode;
  notice?: ReactNode;
}) {
  return (
    <Panel className={cn("overflow-hidden", className)} {...props}>
      {title ? (
        <PanelHeader title={title} action={action} />
      ) : (
        action && (
          <header className="flex flex-wrap items-center justify-end gap-2 border-b px-5 py-3">
            {action}
          </header>
        )
      )}
      {notice && <div className={REVEAL}>{notice}</div>}
      {children}
    </Panel>
  );
}

/** One labelled fact in a row of fixed furniture. */
export function Fact({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("grid min-w-0 gap-0.5", className)}>
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="truncate text-s-400">{children}</dd>
    </div>
  );
}
