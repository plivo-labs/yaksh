import { Bot, Copy, GitFork, Ellipsis, Link2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { toast } from "sonner";

import { DeleteDialog } from "@/components/confirm-dialogs";
import { Pager } from "@/components/pager";
import { SearchInput } from "@/components/search-input";
import { SortHeader } from "@/components/sort-header";
import { Timestamp } from "@/components/timestamp";
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
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilterParams } from "@/hooks/use-filter-params";
import { usePageParam } from "@/hooks/use-page-param";
import { copyText } from "@/lib/clipboard";
import { duration, reach, words } from "@/lib/format";
import {
  AGENTS_PAGE,
  useAgentPage,
  useAgentSources,
  useDeleteAgent,
  useForkAgent,
  useLastCall,
  useScenarioCount,
} from "@/lib/queries";
import { type AgentSource, type AgentSummary, languageNames, SOURCE_NAMES } from "@/lib/types";

const ROW =
  "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-2 px-3 md:grid-cols-[minmax(12rem,1.4fr)_7rem_6rem_minmax(12rem,1fr)_8rem_2rem]";

const ANY = "any";

export function AgentsPage() {
  const [params, update] = useFilterParams();
  const search = params.get("q") ?? "";
  const sort = params.get("sort") ?? "";
  const sources = useAgentSources().data ?? [];
  const source = (Object.keys(SOURCE_NAMES) as AgentSource[]).find(
    (value) => value === params.get("source"),
  );
  const page = usePageParam();
  const agents = useAgentPage(search, source, sort, page);
  const empty = agents.data?.total === 0 && !search && !source;
  const searchFor = (text: string) => update({ q: text });
  const sortBy = (next: string) => update({ sort: next });

  return (
    <div className="grid gap-6">
      <div className="flex min-h-[30px] flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-h3-500">Agents</h1>
        <SearchInput
          value={search}
          onSearch={searchFor}
          label="Search agents"
          placeholder="Search by name, number or id"
          className="order-last basis-full sm:order-none sm:basis-64"
        />
        {(sources.length > 1 || source) && (
          <SourceFilter
            sources={sources}
            value={source}
            onChange={(next) => update({ source: next ?? null })}
          />
        )}
        {!empty && (
          <>
            <Button
              variant="outline"
              size="sm"
              nativeButton={false}
              render={<Link to="/agents/new/provider" />}
            >
              <Link2 />
              Import from a provider
            </Button>
            <Button size="sm" nativeButton={false} render={<Link to="/agents/new" />}>
              <Plus />
              New agent
            </Button>
          </>
        )}
      </div>

      {agents.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load agents</AlertTitle>
          <AlertDescription>{agents.error.message}</AlertDescription>
        </Alert>
      ) : empty ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Bot />
            </EmptyMedia>
            <EmptyTitle>No agents yet</EmptyTitle>
            <EmptyDescription>
              An agent is the phone number Yaksha calls. Add one, give it a scenario, and Yaksha
              phones it with a simulated caller.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent className="flex-row flex-wrap justify-center">
            <Button nativeButton={false} render={<Link to="/agents/new" />}>
              <Plus />
              Add your first agent
            </Button>
            <Button
              variant="outline"
              nativeButton={false}
              render={<Link to="/agents/new/provider" />}
            >
              <Link2 />
              Import from a provider
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <div
          aria-busy={agents.isFetching}
          className={`transition-opacity duration-150 ${agents.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <div className={`${ROW} hidden border-b pb-3 text-label text-secondary md:grid`}>
            <SortHeader label="Agent" field="name" sort={sort} onSort={sortBy} />
            <SortHeader label="Languages" field="languages" sort={sort} onSort={sortBy} />
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
                <li key={index} className={`${ROW} py-3.5`}>
                  <Skeleton className="col-span-full h-10" />
                </li>
              ))
            ) : agents.data.items.length === 0 ? (
              <li className="px-3 py-8 text-p-400 text-muted-foreground">
                {search ? `No agents match “${search}”.` : "No agents from this source."}
              </li>
            ) : (
              agents.data.items.map((agent) => <AgentRow key={agent.id} agent={agent} />)
            )}
          </ul>
          <Pager className="mt-4" query={agents} pageSize={AGENTS_PAGE} />
        </div>
      )}
    </div>
  );
}

/** Shown only when the agents came from more than one place, so one source adds no noise. */
function SourceFilter({
  sources,
  value,
  onChange,
}: {
  sources: AgentSource[];
  value: AgentSource | undefined;
  onChange: (source: AgentSource | undefined) => void;
}) {
  const items = [
    { value: ANY, label: "All sources" },
    ...sources.map((source) => ({ value: source, label: SOURCE_NAMES[source] })),
  ];
  return (
    <Select
      items={items}
      value={value ?? ANY}
      onValueChange={(next) => onChange(sources.find((source) => source === next))}
    >
      <SelectTrigger size="sm" className="w-40" aria-label="Filter by source">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

function AgentRow({ agent }: { agent: AgentSummary }) {
  const last = useLastCall(agent.id);
  const scenarios = useScenarioCount(agent.id);
  const call = last.data;
  return (
    <li
      className={`${ROW} group relative py-3.5 transition-colors duration-150 hover:bg-hv1 has-[a:active]:bg-st2 has-[a:focus-visible]:bg-hv1 has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring/50 has-[a:focus-visible]:ring-inset`}
    >
      <div className="min-w-0">
        <div className="grid min-w-0 gap-0.5">
          <Link
            to={`/agents/${agent.id}`}
            title={agent.name}
            className="truncate text-s-500 outline-none after:absolute after:inset-0 transition-colors"
          >
            {agent.name}
          </Link>
          <span className="text-s-400 text-muted-foreground">{reach(agent)}</span>
        </div>
      </div>
      <div className="col-span-2 text-s-400 md:col-span-1">{languageNames(agent.languages)}</div>
      <div className="col-span-2 text-s-400 md:col-span-1">
        {scenarios.data === undefined ? (
          <Skeleton className="h-4 w-12" />
        ) : (
          <>
            <span className="tabular-nums">{scenarios.data}</span>{" "}
            <span className="text-muted-foreground">
              {scenarios.data === 1 ? "scenario" : "scenarios"}
            </span>
          </>
        )}
      </div>
      <div className="col-span-2 grid min-w-0 gap-0.5 text-s-400 md:col-span-1">
        {last.isPending ? (
          <Skeleton className="h-9 w-40" />
        ) : call ? (
          <>
            <Link
              to={`/conversations/${call.id}`}
              title={call.scenario_name}
              className="relative z-10 w-fit max-w-full truncate rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              {call.scenario_name}
            </Link>
            <span className="truncate text-muted-foreground">
              <span className="capitalize">{words(call.status)}</span>
              {call.talk_ms !== null && `, ${duration(call.talk_ms)}`},{" "}
              <Timestamp iso={call.started_at ?? call.created_at} />
            </span>
          </>
        ) : (
          <span className="text-muted-foreground">Never called</span>
        )}
      </div>
      <div className="col-span-2 text-xs-400 text-muted-foreground md:col-span-1">
        <span className="md:hidden">Updated </span>
        <Timestamp iso={agent.updated_at} />
      </div>
      <AgentMenu agent={agent} />
    </li>
  );
}

function AgentMenu({ agent }: { agent: AgentSummary }) {
  const navigate = useNavigate();
  const fork = useForkAgent();
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
            disabled={fork.isPending}
            onClick={() =>
              fork.mutate(agent.id, {
                onSuccess: (copy) => {
                  toast.success("Fork created", {
                    description: `"${copy.name}" calls the same agent until you change its number or trigger.`,
                    action: {
                      label: "Undo",
                      onClick: () =>
                        void remove.mutateAsync(copy.id).then(() => navigate("/agents")),
                    },
                  });
                  navigate(`/agents/${copy.id}`);
                },
                onError: (error) =>
                  toast.error(`Could not fork ${agent.name}`, { description: error.message }),
              })
            }
          >
            <GitFork />
            Fork
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
