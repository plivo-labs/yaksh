import { ChevronLeft, ChevronRight, PhoneOutgoing } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { CopyId } from "@/components/copy-id";
import { Fact, Panel, PanelHeader } from "@/components/panel";
import { RelativeTime } from "@/components/relative-time";
import { Dot, StatusBadge, StatusDot } from "@/components/status-dot";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { duration, phone, reach, since, when } from "@/lib/format";
import { useAgent, useAgents, useConversations, useLastCall } from "@/lib/queries";
import {
  ACTIVE_STATUSES,
  type Agent,
  type ConversationSummary,
  END_REASON_LABELS,
  LANGUAGE_NAMES,
  type OutboundSettings,
} from "@/lib/types";
import { AgentForm } from "@/pages/agent-form";
import { AgentScenarios } from "@/pages/agent-scenarios";
import { StartCallDialog } from "@/pages/start-call-dialog";

const CALLS_SHOWN = 8;

export function AgentPage() {
  const { id = "" } = useParams();
  const agent = useAgent(id);

  if (agent.isError) {
    return (
      <Alert variant="destructive" className="mx-auto max-w-6xl">
        <AlertTitle>Could not load the agent</AlertTitle>
        <AlertDescription>{agent.error.message}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <Link
        to="/agents"
        className="inline-flex w-fit items-center gap-1 rounded-sm text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        <ChevronLeft className="size-4" />
        Agents
      </Link>
      {agent.isPending ? (
        <Skeleton className="h-40 w-full rounded-lg" />
      ) : (
        <Designation agent={agent.data} />
      )}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="grid gap-6">
          {agent.data && <AgentScenarios agent={agent.data} />}
          {agent.data && <Calls agent={agent.data} />}
        </div>
        {agent.data ? (
          <Settings key={agent.data.id} agent={agent.data} />
        ) : (
          <Skeleton className="h-80 rounded-lg" />
        )}
      </div>
    </div>
  );
}

function Designation({ agent }: { agent: Agent }) {
  const agents = useAgents();
  const last = useLastCall(agent.id);
  return (
    <Panel>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4 px-5 pt-5 pb-4">
        <div className="grid min-w-0 flex-1 basis-72 gap-0.5 sm:flex-none">
          <h1 className="truncate text-2xl font-semibold tracking-[-0.015em]">{agent.name}</h1>
          <p className="text-sm text-muted-foreground">{reach(agent)}</p>
        </div>
        <LineState call={last.data} pending={last.isPending} />
        <StartCallDialog
          agents={agents.data ?? [agent]}
          agentId={agent.id}
          render={<Button size="lg" className="w-full sm:ml-auto sm:w-auto" />}
        >
          <PhoneOutgoing />
          Start call
        </StartCallDialog>
      </div>
    </Panel>
  );
}

function LineState({
  call,
  pending,
}: {
  call: ConversationSummary | null | undefined;
  pending: boolean;
}) {
  if (pending) return <Skeleton className="h-6 w-56" />;
  if (!call) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <Badge variant="outline" className="gap-1.5">
          <Dot tone="off" size="sm" />
          Idle
        </Badge>
        <span className="text-muted-foreground">Never called</span>
      </div>
    );
  }
  const active = ACTIVE_STATUSES.includes(call.status);
  const state =
    call.status === "queued"
      ? "Waiting to dial"
      : call.status === "ending"
        ? "Hanging up"
        : "On a call";
  return (
    <Link
      to={`/conversations/${call.id}`}
      className="-mx-2 flex items-center gap-2 rounded-md px-2 py-1 text-sm outline-none transition-colors hover:bg-foreground/[0.04] focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      <Badge variant="outline" className="gap-1.5">
        {active ? <StatusDot status={call.status} size="sm" /> : <Dot tone="off" size="sm" />}
        {active ? state : "Idle"}
      </Badge>
      <span className="text-muted-foreground">
        {active
          ? call.scenario_name
          : `Last call ${call.status} ${since(call.started_at ?? call.created_at)}`}
      </span>
    </Link>
  );
}

function Calls({ agent }: { agent: Agent }) {
  const agentId = agent.id;
  const calls = useConversations({ agent_id: agentId }, 1);
  const total = calls.data?.total ?? 0;
  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title="Calls"
        action={
          total > CALLS_SHOWN && (
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link to={`/conversations?agent_id=${agentId}`} />}
            >
              All {total} calls
              <ChevronRight />
            </Button>
          )
        }
      />
      {calls.isPending ? (
        <div className="grid gap-3 p-5">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : calls.isError ? (
        <p className="px-5 py-4 text-sm text-destructive">{calls.error.message}</p>
      ) : calls.data.items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-muted-foreground">
          No calls yet. Ring a scenario above to place the first one.
        </p>
      ) : (
        <ul className="divide-y">
          {calls.data.items.slice(0, CALLS_SHOWN).map((call) => (
            <li key={call.id}>
              <Link
                to={`/conversations/${call.id}`}
                className="group grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-5 py-3 outline-none transition-colors duration-150 hover:bg-foreground/[0.025] focus-visible:bg-foreground/[0.04] focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset md:grid-cols-[6.5rem_minmax(0,1.4fr)_minmax(0,1fr)_4.5rem_8rem]"
              >
                <span className="text-sm">
                  <StatusBadge status={call.status} />
                </span>
                <span className="grid min-w-0 gap-0.5 text-sm">
                  <span className="truncate font-medium">{call.scenario_name}</span>
                  <span className="truncate text-muted-foreground">
                    {call.persona_name}
                    {call.agent_version < agent.current_version && ", earlier version"}
                  </span>
                </span>
                <span className="hidden truncate text-sm md:block">
                  {call.end_reason ? (
                    END_REASON_LABELS[call.end_reason]
                  ) : (
                    <span className="capitalize">{call.status}</span>
                  )}
                  {call.failure_reason && (
                    <span className="block truncate text-destructive">{call.failure_reason}</span>
                  )}
                </span>
                <span className="hidden text-right text-sm md:block">
                  {duration(call.talk_ms) || <span className="text-muted-foreground">–</span>}
                </span>
                <span className="text-right text-sm text-muted-foreground">
                  <RelativeTime iso={call.started_at ?? call.created_at} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Settings({ agent }: { agent: Agent }) {
  const [editing, setEditing] = useState(false);
  return (
    <Panel className="lg:sticky lg:top-0">
      <PanelHeader
        title="Settings"
        action={
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            Edit
          </Button>
        }
      />
      <dl className="grid grid-cols-[minmax(0,1fr)] gap-4 px-5 py-4">
        <Fact label="Language">{LANGUAGE_NAMES[agent.language]}</Fact>
        <Fact label="Opens with">
          {agent.agent_speaks_first ? "Agent speaks first" : "Caller speaks first"}
        </Fact>
        {agent.outbound && <OutboundFacts outbound={agent.outbound} />}
        <div className="grid gap-0.5">
          <dt className="text-xs text-muted-foreground">Brief</dt>
          <dd className="text-sm whitespace-pre-wrap">
            {agent.brief ?? <span className="text-muted-foreground">None</span>}
          </dd>
        </div>
        <Fact label="External id">
          {agent.external_id ?? <span className="font-normal text-muted-foreground">None</span>}
        </Fact>
        <Fact label="Agent id">
          <CopyId id={agent.id} label="agent id" />
        </Fact>
        <Fact label="Added">{when(agent.created_at)}</Fact>
      </dl>
      <Sheet open={editing} onOpenChange={setEditing}>
        <SheetContent size="lg" className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Edit {agent.name}</SheetTitle>
          </SheetHeader>
          <div className="px-6 pb-6">
            <AgentForm
              agent={agent}
              onSaved={() => {
                setEditing(false);
                toast.success("Settings saved");
              }}
              cancel={
                <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              }
            />
          </div>
        </SheetContent>
      </Sheet>
    </Panel>
  );
}

/** What Truman sends to start an outbound agent's call, and how it takes the call. */
function OutboundFacts({ outbound }: { outbound: OutboundSettings }) {
  const { trigger } = outbound;
  return (
    <>
      <div className="grid gap-0.5">
        <dt className="text-xs text-muted-foreground">Start request</dt>
        <dd className="text-sm break-all">
          <span className="text-muted-foreground">POST </span>
          {trigger.url}
        </dd>
      </div>
      <Fact label="Headers">
        {trigger.headers.length > 0 ? (
          trigger.headers.map((header) => header.name).join(", ")
        ) : (
          <span className="font-normal text-muted-foreground">None</span>
        )}
      </Fact>
      <div className="grid min-w-0 gap-1">
        <dt className="text-xs text-muted-foreground">Request body</dt>
        <dd className="min-w-0">
          <pre className="max-h-48 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
            {JSON.stringify(trigger.body, null, 2)}
          </pre>
        </dd>
      </div>
      <Fact label="Calling numbers">
        {outbound.calling_numbers.length > 0 ? (
          outbound.calling_numbers.map(phone).join(", ")
        ) : (
          <span className="font-normal text-muted-foreground">Any number</span>
        )}
      </Fact>
      <Fact label="Dial window">{outbound.dial_window_s} seconds</Fact>
    </>
  );
}
