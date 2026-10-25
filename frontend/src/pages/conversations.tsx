import { ConversationList } from "@/components/conversation-list";
import { FilterSelect } from "@/components/filter-select";
import { Pager } from "@/components/pager";
import { SearchInput } from "@/components/search-input";
import { useFilterParams } from "@/hooks/use-filter-params";
import { usePageParam } from "@/hooks/use-page-param";
import { CONVERSATIONS_PAGE, useAgents, useConversations } from "@/lib/queries";
import type { ConversationStatus } from "@/lib/types";

const STATUSES: ConversationStatus[] = [
  "queued",
  "running",
  "ending",
  "completed",
  "failed",
  "invalid",
  "cancelled",
];

const ANY = "any";

export function ConversationsPage() {
  const [params, update] = useFilterParams();
  const agentId = params.get("agent_id") ?? ANY;
  const status = params.get("status") ?? ANY;
  const search = params.get("q") ?? "";
  const sort = params.get("sort") ?? "";
  const page = usePageParam();
  const filters: Record<string, string> = {};
  if (agentId !== ANY) filters.agent_id = agentId;
  if (status !== ANY) filters.status = status;
  if (search) filters.q = search;
  if (sort) filters.sort = sort;
  const agents = useAgents();
  const conversations = useConversations(filters, page);
  const filtered = agentId !== ANY || status !== ANY || search !== "";

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
        <h1 className="text-h3-500">Conversations</h1>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={search}
          onSearch={(text) => setParam("q", text)}
          label="Search conversations"
          placeholder="Search by agent, scenario, persona or id"
          className="basis-full sm:basis-80"
        />
        <FilterSelect
          label="Filter by agent"
          items={agentItems}
          value={agentId}
          onChange={(value) => setParam("agent_id", value)}
          className="min-w-0 flex-1 sm:w-48 sm:flex-none"
        />
        <FilterSelect
          label="Filter by status"
          items={statusItems}
          value={status}
          onChange={(value) => setParam("status", value)}
          className="min-w-0 flex-1 sm:w-40 sm:flex-none"
        />
      </div>

      <div>
        <ConversationList
          query={conversations}
          place="page"
          showAgent
          sort={{ value: sort, onSort: (next) => setParam("sort", next) }}
          empty={filtered ? "No conversations match these filters." : "No conversations yet."}
        />
        <Pager className="mt-4" query={conversations} pageSize={CONVERSATIONS_PAGE} />
      </div>
    </div>
  );
}
