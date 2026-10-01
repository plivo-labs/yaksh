import { Copy, Ellipsis, PhoneOff, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { toast } from "sonner";

import { Pager } from "@/components/pager";
import { RelativeTime } from "@/components/relative-time";
import { SearchInput } from "@/components/search-input";
import { SortHeader } from "@/components/sort-header";
import { StatusBadge } from "@/components/status-dot";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { usePageParam } from "@/hooks/use-page-param";
import { copyText } from "@/lib/clipboard";
import { duration } from "@/lib/format";
import { CONVERSATIONS_PAGE, useAgents, useConversations, useEndConversation } from "@/lib/queries";
import {
  ACTIVE_STATUSES,
  type ConversationStatus,
  type ConversationSummary,
  END_REASON_LABELS,
} from "@/lib/types";
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

const ROW =
  "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-2 px-3 md:grid-cols-[7rem_minmax(12rem,1.3fr)_minmax(9rem,1fr)_minmax(9rem,1fr)_5rem_8rem_2rem]";

export function ConversationsPage() {
  const [params, setParams] = useSearchParams();
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

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value === ANY || value === "") next.delete(key);
    else next.set(key, value);
    next.delete("page");
    setParams(next, { replace: true });
  };

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-4">
        <h1 className="mr-auto text-2xl font-semibold tracking-[-0.015em]">Conversations</h1>
        <StartCallDialog
          agents={agents.data ?? []}
          render={<Button disabled={!agents.data?.length} />}
        >
          <Plus />
          Start conversation
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

      {conversations.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load conversations</AlertTitle>
          <AlertDescription>{conversations.error.message}</AlertDescription>
        </Alert>
      ) : (
        <div
          aria-busy={conversations.isFetching}
          className={`transition-opacity duration-150 ${conversations.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <div className={`${ROW} hidden border-b pb-2.5 text-xs text-muted-foreground md:grid`}>
            <span>Status</span>
            <span>Scenario</span>
            <span>Agent</span>
            <span>End</span>
            <SortHeader
              label="Talk time"
              field="talk_ms"
              sort={sort}
              descendingFirst
              onSort={(next) => setParam("sort", next)}
            />
            <SortHeader
              label="Started"
              field="created_at"
              sort={sort}
              descendingFirst
              onSort={(next) => setParam("sort", next)}
            />
            <span />
          </div>
          <ul className="divide-y border-b">
            {conversations.data === undefined ? (
              [0, 1, 2].map((index) => (
                <li key={index} className={`${ROW} py-4`}>
                  <Skeleton className="h-10" />
                </li>
              ))
            ) : conversations.data.items.length === 0 ? (
              <li className="px-3 py-8 text-sm text-muted-foreground">
                {filtered ? "No conversations match these filters." : "No conversations yet."}
              </li>
            ) : (
              conversations.data.items.map((conversation) => (
                <ConversationRow key={conversation.id} conversation={conversation} />
              ))
            )}
          </ul>
          <Pager className="mt-4" query={conversations} pageSize={CONVERSATIONS_PAGE} />
        </div>
      )}
    </div>
  );
}

function ConversationRow({ conversation }: { conversation: ConversationSummary }) {
  return (
    <li
      className={`${ROW} group relative py-3.5 transition-colors duration-150 hover:bg-foreground/[0.02] has-[a:focus-visible]:bg-foreground/[0.04]`}
    >
      <div className="md:order-none">
        <StatusBadge status={conversation.status} />
      </div>
      <div className="col-span-2 grid min-w-0 gap-0.5 md:col-span-1">
        <Link
          to={`/conversations/${conversation.id}`}
          className="truncate text-sm font-medium outline-none after:absolute after:inset-0"
        >
          {conversation.scenario_name}
        </Link>
        <span className="truncate text-sm text-muted-foreground">{conversation.persona_name}</span>
        <span className="truncate text-sm text-muted-foreground md:hidden">
          {conversation.end_reason ? END_REASON_LABELS[conversation.end_reason] : "In progress"}
          {conversation.talk_ms !== null && `, ${duration(conversation.talk_ms)}`},{" "}
          <RelativeTime iso={conversation.started_at ?? conversation.created_at} />
        </span>
      </div>
      <div className="col-span-2 min-w-0 text-sm md:col-span-1">
        <Link
          to={`/agents/${conversation.agent_id}`}
          className="relative z-10 block w-fit max-w-full truncate rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          {conversation.agent_name}
        </Link>
      </div>
      <div className="hidden min-w-0 gap-0.5 text-sm md:grid">
        {conversation.end_reason ? (
          <span className="truncate">{END_REASON_LABELS[conversation.end_reason]}</span>
        ) : (
          <span className="text-muted-foreground">In progress</span>
        )}
        {conversation.failure_reason && (
          <span className="truncate text-destructive" title={conversation.failure_reason}>
            {conversation.failure_reason}
          </span>
        )}
      </div>
      <div className="hidden text-sm md:block">
        {conversation.talk_ms === null ? (
          <span className="text-muted-foreground">–</span>
        ) : (
          duration(conversation.talk_ms)
        )}
      </div>
      <div className="hidden text-sm text-muted-foreground md:block">
        <RelativeTime iso={conversation.started_at ?? conversation.created_at} />
      </div>
      <ConversationMenu conversation={conversation} />
    </li>
  );
}

function ConversationMenu({ conversation }: { conversation: ConversationSummary }) {
  const end = useEndConversation(conversation.id);
  const [ending, setEnding] = useState(false);
  const active = ACTIVE_STATUSES.includes(conversation.status);
  return (
    <div className="relative z-10 col-start-2 row-start-1 md:col-start-auto md:row-start-auto">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`More actions for ${conversation.scenario_name}`}
            />
          }
        >
          <Ellipsis />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onClick={() => void copyText(conversation.id, "Conversation id copied")}
          >
            <Copy />
            Copy conversation id
          </DropdownMenuItem>
          {active && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={() => setEnding(true)}>
                <PhoneOff />
                End call
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <AlertDialog open={ending} onOpenChange={setEnding}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>End this call?</AlertDialogTitle>
            <AlertDialogDescription>
              {conversation.status === "queued"
                ? "It has not connected yet, so it will be cancelled."
                : "The caller hangs up and what was said so far is kept."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep going</AlertDialogCancel>
            <AlertDialogAction
              disabled={end.isPending}
              onClick={() =>
                end.mutate(undefined, {
                  onSuccess: () => {
                    setEnding(false);
                    toast.success("Ending the call");
                  },
                  onError: (error) =>
                    toast.error("Could not end the call", { description: error.message }),
                })
              }
            >
              End call
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
