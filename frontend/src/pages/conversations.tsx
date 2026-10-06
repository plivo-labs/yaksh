import { Plus } from "lucide-react";

import { ConversationList } from "@/components/conversation-list";
import { Pager } from "@/components/pager";
import { SearchInput } from "@/components/search-input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useFilterParams } from "@/hooks/use-filter-params";
import { usePageParam } from "@/hooks/use-page-param";
import { CONVERSATIONS_PAGE, useAgents, useConversations } from "@/lib/queries";
import type { ConversationStatus } from "@/lib/types";
import { StartCallDialog } from "@/pages/start-call-dialog";

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
      <div className="flex min-h-[30px] flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-h3-500">Conversations</h1>
        <StartCallDialog
          agents={agents.data ?? []}
          render={<Button size="sm" disabled={!agents.data?.length} />}
        >
          <Plus />
          Start call
        </StartCallDialog>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={search}
          onSearch={(text) => setParam("q", text)}
          label="Search conversations"
          placeholder="Search by agent, scenario, persona or id"
          className="basis-full sm:basis-80"
        />
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
