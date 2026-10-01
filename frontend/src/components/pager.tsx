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
import { usePageParam } from "@/hooks/use-page-param";

function withPage(params: URLSearchParams, page: number): URLSearchParams {
  const next = new URLSearchParams(params);
  if (page <= 1) next.delete("page");
  else next.set("page", String(page));
  return next;
}

/** Previous and next links for a list paged through the URL. While the next page loads, the
 * pager stays on screen with the total it has. Once the data is settled, a page past the end,
 * such as after a live list shrinks, goes back to the last page. */
export function Pager({
  query,
  pageSize,
  className,
}: {
  query: { data?: { total: number }; isPlaceholderData: boolean };
  pageSize: number;
  className?: string;
}) {
  const page = usePageParam();
  const [params, setParams] = useSearchParams();
  const total = query.data?.total;
  const last = Math.max(1, Math.ceil((total ?? 0) / pageSize));
  const settled = total !== undefined && !query.isPlaceholderData;
  useEffect(() => {
    if (settled && page > last) setParams((current) => withPage(current, last), { replace: true });
  }, [settled, page, last, setParams]);
  if (total === undefined || total <= pageSize) return null;
  const go = (target: number) => (event: MouseEvent) => {
    event.preventDefault();
    if (target < 1 || target > last) return;
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
