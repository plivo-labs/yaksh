import { Collapsible } from "@base-ui/react/collapsible";
import { cn } from "cn";
import { ChevronRight } from "lucide-react";
import { type ComponentProps, type ReactNode, useState } from "react";

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

export function PanelHeader({ title, action }: { title: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b px-5 py-3.5">
      <h2 className="text-[15px] font-semibold tracking-[-0.005em]">{title}</h2>
      {action}
    </header>
  );
}

/** Whether the panel `name` is folded; the choice carries over in this browser. */
function useFolded(name: string): [boolean, (folded: boolean) => void] {
  const key = `truman.folded.${name}`;
  const [folded, setFolded] = useState(() => {
    try {
      return localStorage.getItem(key) === "true";
    } catch {
      return false;
    }
  });
  const save = (next: boolean) => {
    setFolded(next);
    try {
      localStorage.setItem(key, String(next));
    } catch {
      // storage unavailable: the choice lasts for this page only
    }
  };
  return [folded, save];
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
  const [folded, setFolded] = useFolded(name);
  return (
    <Collapsible.Root
      open={!folded}
      onOpenChange={(open) => setFolded(!open)}
      render={<Panel className={cn("overflow-hidden", className)} {...props} />}
    >
      <PanelHeader
        title={
          <Collapsible.Trigger className="group -mx-1 inline-flex items-center gap-1.5 rounded-sm px-1 outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
            <ChevronRight className="size-4 text-muted-foreground transition-transform duration-150 ease-out group-data-panel-open:rotate-90 motion-reduce:transition-none" />
            {title}
            {count !== undefined && (
              <span className="font-normal text-muted-foreground tabular-nums">{count}</span>
            )}
          </Collapsible.Trigger>
        }
        action={action}
      />
      {notice}
      <Collapsible.Panel className="h-(--collapsible-panel-height) overflow-hidden transition-[height] duration-200 ease-out data-ending-style:h-0 data-starting-style:h-0 motion-reduce:transition-none">
        {children}
      </Collapsible.Panel>
    </Collapsible.Root>
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
