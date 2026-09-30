import { cn } from "cn";
import { type MouseEvent, useEffect } from "react";
import { useSearchParams } from "react-router";

import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";

function withPage(params: URLSearchParams, page: number): URLSearchParams {
  const next = new URLSearchParams(params);
  if (page <= 1) next.delete("page");
  else next.set("page", String(page));
  return next;
}

/** Previous and next links for a list paged through the URL. When a live list shrinks under
 * the page, it goes back to the last page. The total is undefined while the shown data is a
 * placeholder, so a stale total never moves the page. */
export function Pager({
  page,
  total,
  pageSize,
  className,
}: {
  page: number;
  total: number | undefined;
  pageSize: number;
  className?: string;
}) {
  const [params, setParams] = useSearchParams();
  const last = total === undefined ? page : Math.max(1, Math.ceil(total / pageSize));
  useEffect(() => {
    if (page > last) setParams((current) => withPage(current, last), { replace: true });
  }, [page, last, setParams]);
  if (total === undefined || total <= pageSize) return null;
  const go = (target: number) => (event: MouseEvent) => {
    event.preventDefault();
    setParams(withPage(params, target));
  };
  return (
    <Pagination className={cn("justify-between", className)}>
      <span className="text-sm text-muted-foreground tabular-nums">
        {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, total)} of {total}
      </span>
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious
            href={`?${withPage(params, page - 1)}`}
            onClick={go(page - 1)}
            aria-disabled={page <= 1}
            className={page <= 1 ? "pointer-events-none opacity-50" : ""}
          />
        </PaginationItem>
        <PaginationItem>
          <PaginationNext
            href={`?${withPage(params, page + 1)}`}
            onClick={go(page + 1)}
            aria-disabled={page >= last}
            className={page >= last ? "pointer-events-none opacity-50" : ""}
          />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
