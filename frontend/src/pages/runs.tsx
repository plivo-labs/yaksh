import { DateFilter } from "@/components/date-filter";
import { Pager } from "@/components/pager";
import { RunList } from "@/components/run-list";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createdBetween, useDatesParam } from "@/hooks/use-dates-param";
import { useFilterParams } from "@/hooks/use-filter-params";
import { usePageParam } from "@/hooks/use-page-param";
import { RUNS_PAGE, useAgents, useRuns } from "@/lib/queries";
import type { RunStatus } from "@/lib/types";

const STATUSES: RunStatus[] = ["queued", "running", "cancelling", "done", "cancelled"];

const ANY = "any";

/** Every agent's runs, newest first, narrowed by agent, status and dates in the address. */
export function RunsPage() {
  const [params, update] = useFilterParams();
  const agentId = params.get("agent_id") ?? ANY;
  const status = params.get("status") ?? ANY;
  const [dates, setDates] = useDatesParam();
  const agents = useAgents();
  const runs = useRuns(
    {
      agentId: agentId === ANY ? undefined : agentId,
      status: STATUSES.find((value) => value === status),
      ...createdBetween(dates),
    },
    usePageParam(),
  );
  const filtered = agentId !== ANY || status !== ANY || dates !== undefined;

  const agentItems = [
    { value: ANY, label: "All agents" },
    ...(agents.data?.map((agent) => ({ value: agent.id, label: agent.name })) ?? []),
  ];
  const statusItems = [
    { value: ANY, label: "All statuses" },
    ...STATUSES.map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) })),
  ];

  const setParam = (key: string, value: string) => update({ [key]: value === ANY ? null : value });

  return (
    <div className="grid gap-6">
      <div className="flex min-h-[30px] items-center">
        <h1 className="text-h3-500">Runs</h1>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          items={agentItems}
          value={agentId}
          onValueChange={(value) => setParam("agent_id", value ?? ANY)}
        >
          <SelectTrigger
            size="sm"
            className="min-w-0 flex-1 sm:w-48 sm:flex-none"
            aria-label="Filter by agent"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {agentItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          items={statusItems}
          value={status}
          onValueChange={(value) => setParam("status", value ?? ANY)}
        >
          <SelectTrigger
            size="sm"
            className="min-w-0 flex-1 sm:w-40 sm:flex-none"
            aria-label="Filter by status"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {statusItems.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <DateFilter
          dates={dates}
          onDatesChange={setDates}
          className="min-w-0 flex-1 sm:w-auto sm:flex-none"
        />
      </div>

      <div>
        <RunList
          query={runs}
          place="page"
          showAgent
          empty={
            filtered
              ? "No runs match these filters."
              : "No runs yet. Open an agent, select scenarios on its Scenarios tab and click Run."
          }
        />
        <Pager className="mt-4" query={runs} pageSize={RUNS_PAGE} />
      </div>
    </div>
  );
}
