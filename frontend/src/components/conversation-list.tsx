import { cn } from "cn";
import { Copy, Ellipsis, PhoneOff } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { RelativeTime } from "@/components/relative-time";
import { SortHeader } from "@/components/sort-header";
import { StatusBadge } from "@/components/status-dot";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { copyText } from "@/lib/clipboard";
import { duration } from "@/lib/format";
import { useEndConversation } from "@/lib/queries";
import {
  ACTIVE_STATUSES,
  type ConversationSummary,
  END_REASON_LABELS,
  type Page,
} from "@/lib/types";

const COLUMNS = {
  withAgent:
    "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-1 md:grid-cols-[7rem_minmax(12rem,1.3fr)_minmax(9rem,1fr)_minmax(9rem,1fr)_5rem_8rem_2rem]",
  withoutAgent:
    "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-1 md:grid-cols-[7rem_minmax(12rem,1.4fr)_minmax(9rem,1fr)_5rem_8rem_2rem]",
};
const GUTTER = { page: "px-3", panel: "px-5" };

/** Conversations, one row each, with a menu to copy the id or end the call. `place` sets the
 * edges: a list on a page closes with a border, a list in a panel uses the panel's. */
export function ConversationList({
  query,
  empty,
  place,
  showAgent = false,
  agentVersion,
  sort,
}: {
  query: {
    data?: Page<ConversationSummary>;
    error: Error | null;
    isFetching: boolean;
    isPlaceholderData: boolean;
  };
  empty: string;
  place: "page" | "panel";
  showAgent?: boolean;
  /** The agent's current version: rows of an earlier version say so. */
  agentVersion?: number;
  sort?: { value: string; onSort: (sort: string) => void };
}) {
  const grid = cn(showAgent ? COLUMNS.withAgent : COLUMNS.withoutAgent, GUTTER[place]);
  if (query.error) {
    return (
      <p role="alert" className={cn(GUTTER[place], "py-4 text-sm text-destructive")}>
        Could not load the conversations: {query.error.message}
      </p>
    );
  }
  return (
    <div
      aria-busy={query.isFetching}
      className={cn("transition-opacity duration-150", query.isPlaceholderData && "opacity-60")}
    >
      <div className={cn(grid, "hidden border-b py-2.5 text-xs text-muted-foreground md:grid")}>
        <span>Status</span>
        <span>Scenario</span>
        {showAgent && <span>Agent</span>}
        <span>End</span>
        {sort ? (
          <SortHeader
            label="Talk time"
            field="talk_ms"
            sort={sort.value}
            descendingFirst
            onSort={sort.onSort}
          />
        ) : (
          <span>Talk time</span>
        )}
        {sort ? (
          <SortHeader
            label="Started"
            field="created_at"
            sort={sort.value}
            descendingFirst
            onSort={sort.onSort}
          />
        ) : (
          <span>Started</span>
        )}
        <span />
      </div>
      <ul className={cn("divide-y", place === "page" && "border-b")}>
        {query.data === undefined ? (
          [0, 1, 2].map((index) => (
            <li key={index} className={cn(grid, "py-3.5")}>
              <Skeleton className="col-span-full h-10" />
            </li>
          ))
        ) : query.data.items.length === 0 ? (
          <li className={cn(GUTTER[place], "py-6 text-sm text-muted-foreground")}>{empty}</li>
        ) : (
          query.data.items.map((conversation) => (
            <ConversationRow
              key={conversation.id}
              conversation={conversation}
              grid={grid}
              showAgent={showAgent}
              agentVersion={agentVersion}
            />
          ))
        )}
      </ul>
    </div>
  );
}

function ConversationRow({
  conversation,
  grid,
  showAgent,
  agentVersion,
}: {
  conversation: ConversationSummary;
  grid: string;
  showAgent: boolean;
  agentVersion: number | undefined;
}) {
  const claim = conversation.caller_claim;
  const end = conversation.end_reason ? (
    END_REASON_LABELS[conversation.end_reason]
  ) : (
    <span className="capitalize">{conversation.status}</span>
  );
  const started = conversation.started_at ? (
    <RelativeTime iso={conversation.started_at} />
  ) : ACTIVE_STATUSES.includes(conversation.status) ? (
    "Not yet"
  ) : (
    "Never"
  );
  return (
    <li
      className={cn(
        grid,
        "group relative py-3.5 transition-colors duration-150 hover:bg-foreground/[0.02] has-[a:focus-visible]:bg-foreground/[0.04]",
      )}
    >
      <div>
        <StatusBadge status={conversation.status} />
      </div>
      <div className="col-span-2 grid min-w-0 gap-0.5 md:col-span-1">
        <span className="flex min-w-0 items-center gap-2">
          <Link
            to={`/conversations/${conversation.id}`}
            className="truncate text-sm font-medium outline-none after:absolute after:inset-0"
          >
            {conversation.scenario_name}
          </Link>
          {conversation.attempt > 1 && (
            <Badge variant="outline" className="shrink-0">
              Attempt {conversation.attempt}
            </Badge>
          )}
        </span>
        <span className="truncate text-sm text-muted-foreground">
          {conversation.persona_name}
          {conversation.repeat !== null && `, repeat ${conversation.repeat}`}
          {agentVersion !== undefined &&
            conversation.agent_version < agentVersion &&
            ", earlier version"}
          {claim &&
            `. Caller claims it ${claim.success ? "reached" : "did not reach"} its goal (not judged)`}
        </span>
        <span className="truncate text-sm text-muted-foreground md:hidden">
          {end}
          {conversation.talk_ms !== null && `, ${duration(conversation.talk_ms)}`}, {started}
        </span>
      </div>
      {showAgent && (
        <div className="col-span-2 min-w-0 text-sm md:col-span-1">
          <Link
            to={`/agents/${conversation.agent_id}`}
            className="relative z-10 block w-fit max-w-full truncate rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {conversation.agent_name}
          </Link>
        </div>
      )}
      <div className="hidden min-w-0 gap-0.5 text-sm md:grid">
        <span className="truncate">{end}</span>
        {conversation.failure_reason && (
          <span className="truncate text-destructive" title={conversation.failure_reason}>
            {conversation.failure_reason}
          </span>
        )}
      </div>
      <div className="hidden text-sm tabular-nums md:block">
        {duration(conversation.talk_ms) || <span className="text-muted-foreground">None</span>}
      </div>
      <div className="hidden text-sm text-muted-foreground md:block">{started}</div>
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
