import { Copy, Ellipsis, PhoneOff } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { EndCallDialog } from "@/components/confirm-dialogs";
import { RelativeTime } from "@/components/relative-time";
import { ResponseTime } from "@/components/response-time";
import { SortHeader } from "@/components/sort-header";
import { ConversationStatusLabel } from "@/components/status-label";
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
import { duration, noiseLabel, when } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  ACTIVE_STATUSES,
  type ConversationSummary,
  END_REASON_LABELS,
  type Page,
} from "@/lib/types";

/** Columns follow the list's own width, not the window's: the same list sits in a full page
 * and in a narrow panel. */
const COLUMNS = {
  withAgent:
    "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-1 @3xl/conversations:grid-cols-[6.5rem_minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_6rem_7rem_8rem_2rem]",
  withoutAgent:
    "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-4 gap-y-1 @3xl/conversations:grid-cols-[6.5rem_minmax(0,2fr)_minmax(0,1fr)_6rem_7rem_8rem_2rem]",
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
      className={cn(
        "@container/conversations transition-opacity duration-150",
        query.isPlaceholderData && "opacity-60",
      )}
    >
      <div
        className={cn(
          grid,
          "hidden border-b py-3 text-label text-muted-foreground @3xl/conversations:grid",
        )}
      >
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
            label="Response p90"
            field="response_p90_ms"
            sort={sort.value}
            descendingFirst
            onSort={sort.onSort}
          />
        ) : (
          <span>Response p90</span>
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
  const name = label(conversation);
  const end = conversation.end_reason && END_REASON_LABELS[conversation.end_reason];
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
        "group relative py-3.5 transition-colors duration-150 hover:bg-muted/60 has-[a:active]:bg-muted has-[a:focus-visible]:bg-muted has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring/50 has-[a:focus-visible]:ring-inset",
      )}
    >
      <div>
        <ConversationStatusLabel status={conversation.status} />
      </div>
      <div className="col-span-2 grid min-w-0 gap-0.5 @3xl/conversations:col-span-1">
        <span className="flex min-w-0 items-center gap-2">
          <Link
            to={`/conversations/${conversation.id}`}
            aria-label={name}
            title={[conversation.scenario_name, conversation.failure_reason]
              .filter(Boolean)
              .join("\n")}
            className="truncate text-s-500 outline-none transition-colors after:absolute after:inset-0 group-hover:text-brand-text"
          >
            {conversation.scenario_name}
          </Link>
          {conversation.attempt > 1 && (
            <Badge className="shrink-0">Attempt {conversation.attempt}</Badge>
          )}
          {noiseLabel(conversation.background_noise) && (
            <Badge className="shrink-0">{noiseLabel(conversation.background_noise)}</Badge>
          )}
        </span>
        <span className="truncate text-s-400 text-muted-foreground">
          {conversation.persona_name}
          {conversation.repeat !== null && `, repeat ${conversation.repeat}`}
          {agentVersion !== undefined &&
            conversation.agent_version < agentVersion &&
            ", earlier version"}
        </span>
        <span className="truncate text-s-400 text-muted-foreground @3xl/conversations:hidden">
          {end && `${end}, `}
          {conversation.talk_ms !== null && `${duration(conversation.talk_ms)}, `}
          {started}
        </span>
      </div>
      {showAgent && (
        <div className="col-span-2 min-w-0 text-s-400 @3xl/conversations:col-span-1">
          <Link
            to={`/agents/${conversation.agent_id}`}
            title={conversation.agent_name}
            className="relative z-10 block w-fit max-w-full truncate rounded-sm underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {conversation.agent_name}
          </Link>
        </div>
      )}
      <div className="hidden min-w-0 gap-0.5 text-s-400 @3xl/conversations:grid">
        <span className="truncate">{end}</span>
        {conversation.failure_reason && (
          <span className="truncate text-destructive">{conversation.failure_reason}</span>
        )}
      </div>
      <div className="hidden font-mono text-xs-400 tabular-nums @3xl/conversations:block">
        {duration(conversation.talk_ms)}
      </div>
      <div className="hidden text-s-400 @3xl/conversations:block">
        {typeof conversation.latency?.p90_ms === "number" && (
          <ResponseTime ms={conversation.latency.p90_ms} />
        )}
      </div>
      <div className="hidden font-mono text-xs-400 @3xl/conversations:block">{started}</div>
      <ConversationMenu conversation={conversation} name={name} />
    </li>
  );
}

/** The scenario with what tells this row from the others of that scenario, in any run. The
 * id ends it because two rows can share everything else down to the minute; its last
 * characters are random, its first ones are a timestamp. */
function label(conversation: ConversationSummary): string {
  const parts = [conversation.scenario_name, conversation.persona_name];
  if (conversation.repeat !== null) parts.push(`repeat ${conversation.repeat}`);
  if (conversation.attempt > 1) parts.push(`attempt ${conversation.attempt}`);
  const noise = noiseLabel(conversation.background_noise);
  if (noise) parts.push(`background noise ${noise}`);
  parts.push(conversation.status, when(conversation.started_at ?? conversation.created_at));
  parts.push(`id ${conversation.id.slice(-8)}`);
  return parts.join(", ");
}

function ConversationMenu({
  conversation,
  name,
}: {
  conversation: ConversationSummary;
  name: string;
}) {
  const [ending, setEnding] = useState(false);
  const active = ACTIVE_STATUSES.includes(conversation.status);
  return (
    <div className="relative z-10 col-start-2 row-start-1 @3xl/conversations:col-start-auto @3xl/conversations:row-start-auto">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button variant="ghost" size="icon-sm" aria-label={`More actions for ${name}`} />}
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
      <EndCallDialog conversation={conversation} open={ending} onOpenChange={setEnding} />
    </div>
  );
}
