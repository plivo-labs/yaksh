import { Collapsible } from "@base-ui/react/collapsible";
import { ChevronRight } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { useStoredBoolean } from "@/hooks/use-stored-boolean";
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

/** A panel whose body folds away under its header, so a long list does not push the panels
 * below out of reach. `notice` stays in view while the body is folded. */
export function FoldingPanel({
  name,
  title,
  count,
  action,
  notice,
  className,
  children,
  ...props
}: Omit<ComponentProps<"section">, "title"> & {
  /** Keys the remembered choice. */
  name: string;
  title: string;
  count?: number;
  action?: ReactNode;
  notice?: ReactNode;
}) {
  const [folded, setFolded] = useStoredBoolean(`truman.folded.${name}`, false);
  return (
    <Collapsible.Root
      open={!folded}
      onOpenChange={(open) => setFolded(!open)}
      render={<Panel className={cn("overflow-hidden", className)} {...props} />}
    >
      <PanelHeader
        title={
          <Collapsible.Trigger className="group -mx-1 inline-flex items-center gap-1.5 rounded-sm px-1 outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
            <ChevronRight className="size-3.5 text-placeholder transition-transform duration-150 ease-out group-data-panel-open:rotate-90 motion-reduce:transition-none" />
            {title}
            {count !== undefined && (
              <span className="font-normal text-muted-foreground tabular-nums">{count}</span>
            )}
          </Collapsible.Trigger>
        }
        action={action}
      />
      {notice && <div className={REVEAL}>{notice}</div>}
      <Collapsible.Panel className="h-(--collapsible-panel-height) overflow-hidden transition-[height] duration-200 ease-out data-ending-style:h-0 data-starting-style:h-0 motion-reduce:transition-none">
        {children}
      </Collapsible.Panel>
    </Collapsible.Root>
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
