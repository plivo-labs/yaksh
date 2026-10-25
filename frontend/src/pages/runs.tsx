import { DateFilter } from "@/components/date-filter";
import { FilterSelect } from "@/components/filter-select";
import { Pager } from "@/components/pager";
import { RunList } from "@/components/run-list";
import { TransportFilter } from "@/components/transport-filter";
import { createdBetween, useDatesParam } from "@/hooks/use-dates-param";
import { useFilterParams } from "@/hooks/use-filter-params";
import { usePageParam } from "@/hooks/use-page-param";
import { useTransportParam } from "@/hooks/use-transport-param";
import { RUNS_PAGE, useAgents, useAllSuites, useRuns } from "@/lib/queries";
import type { RunStatus } from "@/lib/types";

const STATUSES: RunStatus[] = ["queued", "running", "cancelling", "done", "cancelled"];

const ANY = "any";

/** Every agent's runs, newest first, narrowed by agent, status and dates in the address. */
export function RunsPage() {
  const [params, update] = useFilterParams();
  const agentId = params.get("agent_id") ?? ANY;
  const suiteId = params.get("suite_id") ?? ANY;
  const status = params.get("status") ?? ANY;
  const [transport, setTransport] = useTransportParam();
  const [dates, setDates] = useDatesParam();
  const agents = useAgents();
  const suites = useAllSuites();
  const runs = useRuns(
    {
      agentId: agentId === ANY ? undefined : agentId,
      suiteId: suiteId === ANY ? undefined : suiteId,
      transport,
      status: STATUSES.find((value) => value === status),
      ...createdBetween(dates),
    },
    usePageParam(),
  );
  const filtered =
    agentId !== ANY ||
    suiteId !== ANY ||
    status !== ANY ||
    transport !== undefined ||
    dates !== undefined;

  const agentItems = [
    { value: ANY, label: "All agents" },
    ...(agents.data?.map((agent) => ({ value: agent.id, label: agent.name })) ?? []),
  ];
  const suiteItems = [
    { value: ANY, label: "All suites" },
    ...(suites.data?.map((suite) => ({ value: suite.id, label: suite.name })) ?? []),
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
        <FilterSelect
          label="Filter by agent"
          items={agentItems}
          value={agentId}
          onChange={(value) => setParam("agent_id", value)}
          className="min-w-0 flex-1 sm:w-48 sm:flex-none"
        />
        {(suites.data?.length ?? 0) > 0 && (
          <FilterSelect
            label="Filter by suite"
            items={suiteItems}
            value={suiteId}
            onChange={(value) => setParam("suite_id", value)}
            className="min-w-0 flex-1 sm:w-44 sm:flex-none"
          />
        )}
        <FilterSelect
          label="Filter by status"
          items={statusItems}
          value={status}
          onChange={(value) => setParam("status", value)}
          className="min-w-0 flex-1 sm:w-40 sm:flex-none"
        />
        <TransportFilter
          transport={transport}
          onTransportChange={setTransport}
          className="min-w-0 flex-1 sm:w-36 sm:flex-none"
        />
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
