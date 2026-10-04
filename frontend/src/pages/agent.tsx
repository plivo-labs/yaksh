import { ChevronRight, PhoneOutgoing } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { BackButton } from "@/components/back-button";
import { CopyId } from "@/components/copy-id";
import { ConversationList } from "@/components/conversation-list";
import { Fact, FoldingPanel, Panel, PanelHeader } from "@/components/panel";
import { Settle } from "@/components/settle";
import { StatusLabel } from "@/components/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { phone, reach, since, textSize, when } from "@/lib/format";
import { useAgent, useAgents, useConversations, useLastCall } from "@/lib/queries";
import { CONVERSATION_TONE } from "@/lib/status";
import {
  ACTIVE_STATUSES,
  type Agent,
  type ConversationSummary,
  LANGUAGE_NAMES,
  type OutboundSettings,
} from "@/lib/types";
import { EditAgentSheet } from "@/pages/agent-form";
import { AgentKnowledgeBase } from "@/pages/agent-knowledge-base";
import { AgentRuns } from "@/pages/agent-runs";
import { AgentScenarios } from "@/pages/agent-scenarios";
import { StartCallDialog } from "@/pages/start-call-dialog";

const CALLS_SHOWN = 8;

export function AgentPage() {
  const { id = "" } = useParams();
  const agent = useAgent(id);

  if (agent.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the agent</AlertTitle>
        <AlertDescription>{agent.error.message}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="grid gap-6">
      {agent.isPending ? (
        <Skeleton className="h-24 w-full rounded-lg" />
      ) : (
        <Designation agent={agent.data} />
      )}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="grid gap-6">
          {agent.data ? (
            <>
              <AgentScenarios agent={agent.data} />
              <AgentRuns agent={agent.data} />
              <AgentKnowledgeBase agent={agent.data} />
              <Calls agent={agent.data} />
            </>
          ) : (
            <>
              <Skeleton className="h-14 rounded-lg" />
              <Skeleton className="h-14 rounded-lg" />
            </>
          )}
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
        <div className="grid min-w-0 flex-1 basis-72 gap-1">
          <div className="flex min-w-0 items-center gap-2">
            <BackButton fallback="/agents" />
            <h1 className="truncate text-h3-500">{agent.name}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-s-400">
            <span className="text-muted-foreground">{reach(agent)}</span>
            <LineState call={last.data} pending={last.isPending} />
          </div>
        </div>
        <StartCallDialog
          agents={agents.data ?? [agent]}
          agentId={agent.id}
          render={<Button size="sm" className="w-full sm:ml-auto sm:w-auto" />}
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
        <StatusLabel tone="off">Idle</StatusLabel>
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
      className="-mx-2 flex items-center gap-2 rounded-md px-2 py-1 text-s-400 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      <Settle value={active ? state : "Idle"}>
        <StatusLabel
          tone={active ? CONVERSATION_TONE[call.status] : "off"}
          live={call.status === "running"}
        >
          {active ? state : "Idle"}
        </StatusLabel>
      </Settle>
      <span className="text-muted-foreground">
        {active
          ? call.scenario_name
          : `Last call ${call.status} ${since(call.started_at ?? call.created_at)}`}
      </span>
    </Link>
  );
}

function Calls({ agent }: { agent: Agent }) {
  const calls = useConversations({ agent_id: agent.id }, 1, { pageSize: CALLS_SHOWN });
  const total = calls.data?.total ?? 0;
  return (
    <FoldingPanel
      name="calls"
      title="Calls"
      count={calls.data?.total}
      action={
        total > CALLS_SHOWN && (
          <Button
            variant="ghost"
            size="sm"
            nativeButton={false}
            render={<Link to={`/conversations?agent_id=${agent.id}`} />}
          >
            All {total} calls
            <ChevronRight />
          </Button>
        )
      }
    >
      <ConversationList
        query={calls}
        place="panel"
        agentVersion={agent.current_version}
        empty="No calls yet. Ring a scenario above to place the first one."
      />
    </FoldingPanel>
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
        <Fact label="Config">
          {agent.config ? (
            textSize(agent.config.length)
          ) : (
            <span className="font-normal text-muted-foreground">None</span>
          )}
        </Fact>
        <Fact label="External id">
          {agent.external_id ?? <span className="font-normal text-muted-foreground">None</span>}
        </Fact>
        <Fact label="Agent id">
          <CopyId id={agent.id} label="agent id" />
        </Fact>
        <Fact label="Added">{when(agent.created_at)}</Fact>
      </dl>
      {editing && <EditAgentSheet agent={agent} onClosed={() => setEditing(false)} />}
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
