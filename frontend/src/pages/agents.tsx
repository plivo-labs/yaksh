import { Copy, CopyPlus, Ellipsis, Plus, Trash2 } from "lucide-react";
import { type MouseEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { toast } from "sonner";

import { DeleteDialog } from "@/components/confirm-dialogs";
import { SearchInput } from "@/components/search-input";
import { SortHeader } from "@/components/sort-header";
import { RelativeTime } from "@/components/relative-time";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { copyText } from "@/lib/clipboard";
import { duration, reach, words } from "@/lib/format";
import {
  AGENTS_PAGE,
  useAgentPage,
  useDeleteAgent,
  useDuplicateAgent,
  useLastCall,
  useScenarioCount,
} from "@/lib/queries";
import { type AgentSummary, LANGUAGE_NAMES } from "@/lib/types";

const ROW =
  "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-2 px-3 md:grid-cols-[minmax(12rem,1.4fr)_7rem_6rem_minmax(12rem,1fr)_8rem_2rem]";

export function AgentsPage() {
  const [params, setParams] = useSearchParams();
  const search = params.get("q") ?? "";
  const sort = params.get("sort") ?? "";
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const agents = useAgentPage(search, sort, page);
  const searchFor = (text: string) => {
    const next = new URLSearchParams(params);
    if (text) next.set("q", text);
    else next.delete("q");
    next.delete("page");
    setParams(next, { replace: true });
  };
  const sortBy = (next: string) => {
    const target = new URLSearchParams(params);
    target.set("sort", next);
    target.delete("page");
    setParams(target, { replace: true });
  };
  const pageParams = (target: number) => {
    const next = new URLSearchParams(params);
    if (target <= 1) next.delete("page");
    else next.set("page", String(target));
    return next;
  };
  const goTo = (target: number) => (event: MouseEvent) => {
    event.preventDefault();
    setParams(pageParams(target));
  };
  const total = agents.data?.total ?? 0;
  const last = Math.max(1, Math.ceil(total / AGENTS_PAGE));

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-2xl font-semibold tracking-[-0.015em]">Agents</h1>
        <SearchInput
          value={search}
          onSearch={searchFor}
          label="Search agents"
          placeholder="Search by name, number or id"
          className="order-last basis-full sm:order-none sm:basis-64"
        />
        <Button nativeButton={false} render={<Link to="/agents/new" />}>
          <Plus />
          New agent
        </Button>
      </div>

      {agents.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load agents</AlertTitle>
          <AlertDescription>{agents.error.message}</AlertDescription>
        </Alert>
      ) : agents.data?.total === 0 && !search ? (
        <div className="grid justify-items-start gap-4 border-y py-10">
          <div className="grid max-w-md gap-1.5">
            <h2 className="text-lg font-semibold">No agents yet</h2>
            <p className="text-sm text-muted-foreground">
              An agent is the phone number Truman calls. Add one, give it a scenario, and Truman
              phones it with a simulated caller.
            </p>
          </div>
          <Button nativeButton={false} render={<Link to="/agents/new" />}>
            <Plus />
            Add your first agent
          </Button>
        </div>
      ) : (
        <div
          aria-busy={agents.isFetching}
          className={`transition-opacity duration-150 ${agents.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <div className={`${ROW} hidden border-b pb-2.5 text-xs text-muted-foreground md:grid`}>
            <SortHeader label="Agent" field="name" sort={sort} onSort={sortBy} />
            <SortHeader label="Language" field="language" sort={sort} onSort={sortBy} />
            <span>Scenarios</span>
            <span>Last call</span>
            <SortHeader
              label="Last updated"
              field="updated_at"
              sort={sort}
              descendingFirst
              onSort={sortBy}
            />
            <span />
          </div>
          <ul className="divide-y border-b">
            {agents.data === undefined ? (
              [0, 1, 2].map((index) => (
                <li key={index} className={`${ROW} py-4`}>
                  <Skeleton className="h-10" />
                </li>
              ))
            ) : agents.data.items.length === 0 ? (
              <li className="px-3 py-8 text-sm text-muted-foreground">
                No agents match “{search}”.
              </li>
            ) : (
              agents.data.items.map((agent) => <AgentRow key={agent.id} agent={agent} />)
            )}
          </ul>
          {total > AGENTS_PAGE && (
            <Pagination className="mt-4 justify-between">
              <span className="text-sm text-muted-foreground">
                {(page - 1) * AGENTS_PAGE + 1}–{Math.min(page * AGENTS_PAGE, total)} of {total}
              </span>
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    href={`?${pageParams(page - 1)}`}
                    onClick={goTo(page - 1)}
                    aria-disabled={page <= 1}
                    className={page <= 1 ? "pointer-events-none opacity-50" : ""}
                  />
                </PaginationItem>
                <PaginationItem>
                  <PaginationNext
                    href={`?${pageParams(page + 1)}`}
                    onClick={goTo(page + 1)}
                    aria-disabled={page >= last}
                    className={page >= last ? "pointer-events-none opacity-50" : ""}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          )}
        </div>
      )}
    </div>
  );
}

function AgentRow({ agent }: { agent: AgentSummary }) {
  const last = useLastCall(agent.id);
  const scenarios = useScenarioCount(agent.id);
  const call = last.data;
  return (
    <li
      className={`${ROW} group relative py-3.5 transition-colors duration-150 hover:bg-foreground/[0.02] has-[a:focus-visible]:bg-foreground/[0.04]`}
    >
      <div className="min-w-0">
        <div className="grid min-w-0 gap-0.5">
          <Link
            to={`/agents/${agent.id}`}
            className="truncate text-[15px] font-semibold outline-none after:absolute after:inset-0"
          >
            {agent.name}
          </Link>
          <span className="text-sm text-muted-foreground">{reach(agent)}</span>
        </div>
      </div>
      <div className="col-span-2 text-sm md:col-span-1">{LANGUAGE_NAMES[agent.language]}</div>
      <div className="col-span-2 text-sm md:col-span-1">
        {scenarios.data === undefined ? (
          <Skeleton className="h-4 w-12" />
        ) : (
          <>
            <span className="font-semibold">{scenarios.data}</span>{" "}
            <span className="text-muted-foreground">
              {scenarios.data === 1 ? "scenario" : "scenarios"}
            </span>
          </>
        )}
      </div>
      <div className="col-span-2 grid min-w-0 gap-0.5 text-sm md:col-span-1">
        {last.isPending ? (
          <Skeleton className="h-9 w-40" />
        ) : call ? (
          <>
            <Link
              to={`/conversations/${call.id}`}
              className="relative z-10 w-fit max-w-full truncate rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              {call.scenario_name}
            </Link>
            <span className="truncate text-muted-foreground">
              <span className="capitalize">{words(call.status)}</span>
              {call.talk_ms !== null && `, ${duration(call.talk_ms)}`},{" "}
              <RelativeTime iso={call.started_at ?? call.created_at} />
            </span>
          </>
        ) : (
          <span className="text-muted-foreground">Never called</span>
        )}
      </div>
      <div className="col-span-2 text-sm text-muted-foreground md:col-span-1">
        <span className="md:hidden">Updated </span>
        <RelativeTime iso={agent.updated_at} />
      </div>
      <AgentMenu agent={agent} />
    </li>
  );
}

function AgentMenu({ agent }: { agent: AgentSummary }) {
  const navigate = useNavigate();
  const duplicate = useDuplicateAgent();
  const remove = useDeleteAgent();
  const [deleting, setDeleting] = useState(false);
  return (
    <div className="relative z-10 col-start-2 row-start-1 md:col-start-auto md:row-start-auto">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant="ghost" size="icon-sm" aria-label={`More actions for ${agent.name}`} />
          }
        >
          <Ellipsis />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => void copyText(agent.id, "Agent id copied")}>
            <Copy />
            Copy agent id
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={duplicate.isPending}
            onClick={() =>
              duplicate.mutate(agent.id, {
                onSuccess: (copy) => {
                  toast.success(`Duplicated as ${copy.name}`);
                  navigate(`/agents/${copy.id}`);
                },
                onError: (error) =>
                  toast.error(`Could not duplicate ${agent.name}`, { description: error.message }),
              })
            }
          >
            <CopyPlus />
            Duplicate
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onClick={() => setDeleting(true)}>
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <DeleteDialog
        name={agent.name}
        description="Its scenarios are deleted too. Past conversations keep their copy of its configuration."
        pending={remove.isPending}
        error={remove.error?.message}
        open={deleting}
        onOpenChange={(open) => {
          setDeleting(open);
          if (!open) remove.reset();
        }}
        onDelete={(close) =>
          remove.mutate(agent.id, {
            onSuccess: () => {
              close();
              toast.success(`Deleted ${agent.name}`);
            },
          })
        }
      />
    </div>
  );
}
