import { ChevronDown, Copy, Pencil } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { CopyId } from "@/components/copy-id";
import { DateFilter } from "@/components/date-filter";
import { ActionPanel, Fact, Panel, PanelHeader } from "@/components/panel";
import { Pager } from "@/components/pager";
import { RunList } from "@/components/run-list";
import { Settle } from "@/components/settle";
import { StatusLabel } from "@/components/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { createdBetween, useDatesParam } from "@/hooks/use-dates-param";
import { usePageParam } from "@/hooks/use-page-param";
import { copyText } from "@/lib/clipboard";
import { phone, reach, textSize, when } from "@/lib/format";
import { RUNS_PAGE, useAgent, useLastCall, useRuns } from "@/lib/queries";
import { CONVERSATION_TONE } from "@/lib/status";
import {
  ACTIVE_STATUSES,
  type Agent,
  type ConversationSummary,
  languageNames,
  type OutboundSettings,
  SOURCE_NAMES,
} from "@/lib/types";
import { EditAgentSheet } from "@/pages/agent-form";
import { AgentKnowledgeBase } from "@/pages/agent-knowledge-base";
import { AgentRules } from "@/pages/agent-rules";
import { ForkedFrom } from "@/components/forked-from";
import { AgentScenarios } from "@/pages/agent-scenarios";

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
      {agent.data ? (
        <AgentTabs agent={agent.data} />
      ) : (
        <div className="grid gap-4">
          <Skeleton className="h-9 rounded-lg" />
          <Skeleton className="h-64 rounded-lg" />
        </div>
      )}
    </div>
  );
}

const TABS = [
  { value: "config", label: "Config" },
  { value: "scenarios", label: "Scenarios" },
  { value: "runs", label: "Runs" },
] as const;

type Tab = (typeof TABS)[number]["value"];

/** The agent's work, in tabs. The tab is in the address, so a link or a reload keeps it.
 * Every tab stays mounted: a scenario generation or an upload goes on while another tab is open.
 * The rules mount only while Config is open, so their results load again each time it opens. */
function AgentTabs({ agent }: { agent: Agent }) {
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.find((item) => item.value === params.get("tab"))?.value ?? "scenarios";
  const show = (next: Tab) => {
    const target = new URLSearchParams(params);
    target.set("tab", next);
    setParams(target, { replace: true });
  };
  return (
    <Tabs value={tab} onValueChange={(next) => show(next as Tab)} className="min-w-0 gap-4">
      <TabsList variant="line">
        {TABS.map((item) => (
          <TabsTrigger key={item.value} value={item.value}>
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent keepMounted value="config">
        <AgentConfig key={agent.id} agent={agent} active={tab === "config"} />
      </TabsContent>
      <TabsContent keepMounted value="scenarios">
        <AgentScenarios agent={agent} />
      </TabsContent>
      <TabsContent keepMounted value="runs">
        <Runs agent={agent} />
      </TabsContent>
    </Tabs>
  );
}

function Designation({ agent }: { agent: Agent }) {
  const last = useLastCall(agent.id);
  return (
    <Panel>
      <div className="grid min-w-0 gap-1 px-5 pt-5 pb-4">
        <h1 className="truncate text-h3-500" title={agent.name}>
          {agent.name}
        </h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-s-400">
          <span className="text-muted-foreground">{reach(agent)}</span>
          <LineState call={last.data} pending={last.isPending} />
          <ForkedFrom kind="agent" id={agent.forked_from_id} />
        </div>
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
      <div className="flex items-center gap-2 text-p-400">
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
      className="-mx-2 flex items-center gap-2 rounded-md px-2 py-1 text-s-400 outline-none transition-colors hover:bg-hv1 focus-visible:ring-2 focus-visible:ring-ring/50"
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
          : `Last call ${call.status} ${when(call.started_at ?? call.created_at)}`}
      </span>
    </Link>
  );
}

function Runs({ agent }: { agent: Agent }) {
  const [dates, setDates] = useDatesParam();
  const runs = useRuns({ agentId: agent.id, ...createdBetween(dates) }, usePageParam());
  return (
    <ActionPanel action={<DateFilter dates={dates} onDatesChange={setDates} />}>
      <RunList
        query={runs}
        place="panel"
        empty={
          dates
            ? "No runs in these dates."
            : "No runs yet. Select scenarios on the Scenarios tab and click Run."
        }
      />
      <Pager className="border-t px-5 py-3" query={runs} pageSize={RUNS_PAGE} />
    </ActionPanel>
  );
}

/** What the agent does, in the wide column, and its settings, knowledge base and rules beside it.
 * Both Edit buttons open the same sheet. */
function AgentConfig({ agent, active }: { agent: Agent; active: boolean }) {
  const [editing, setEditing] = useState(false);
  const edit = (
    <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
      <Pencil />
      Edit
    </Button>
  );
  return (
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <Purpose agent={agent} edit={edit} />
      <div className="grid gap-6">
        <Settings agent={agent} edit={edit} />
        <AgentKnowledgeBase agent={agent} />
        {active && <AgentRules agent={agent} />}
      </div>
      {editing && <EditAgentSheet agent={agent} onClosed={() => setEditing(false)} />}
    </div>
  );
}

function Purpose({ agent, edit }: { agent: Agent; edit: ReactNode }) {
  const { config } = agent;
  return (
    <Panel>
      <PanelHeader title="What it does" action={edit} />
      <dl className="grid gap-5 px-5 py-4">
        <div className="grid gap-1">
          <dt className="text-xs-400 text-muted-foreground">Brief</dt>
          <dd className="text-p-400 whitespace-pre-wrap">{agent.brief}</dd>
        </div>
        <div className="grid min-w-0 gap-1">
          <dt className="flex min-h-6 items-center gap-2 text-xs-400 text-muted-foreground">
            Config
            {config && (
              <>
                <span>{textSize(config.length)}</span>
                <Button
                  variant="ghost"
                  size="xs"
                  className="ml-auto"
                  onClick={() => void copyText(config, "Config copied")}
                >
                  <Copy />
                  Copy
                </Button>
              </>
            )}
          </dt>
          <dd className="min-w-0">
            {config ? (
              <pre className="max-h-160 overflow-auto rounded-md bg-muted p-3 font-mono text-xs-400 leading-relaxed whitespace-pre-wrap wrap-anywhere">
                {config}
              </pre>
            ) : (
              <span className="text-p-400 text-muted-foreground">None</span>
            )}
          </dd>
        </div>
      </dl>
    </Panel>
  );
}

/** The agent's identity first, and how it calls under "Show more". "Number" is the number Yaksh
 * dials, or for an outbound agent the numbers it may call from; a text agent has its URL. */
function Settings({ agent, edit }: { agent: Agent; edit: ReactNode }) {
  const { outbound, endpoint } = agent;
  const none = <span className="font-normal text-muted-foreground">None</span>;
  return (
    <Panel>
      <PanelHeader title="Settings" action={edit} />
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 px-5 pt-4">
        {endpoint ? (
          <Fact label="Text URL" wrap>
            <span className="break-all">{endpoint.url}</span>
          </Fact>
        ) : (
          <Fact label="Number" wrap>
            {outbound ? (
              outbound.calling_numbers.length > 0 ? (
                outbound.calling_numbers.map(phone).join(", ")
              ) : (
                <span className="font-normal text-muted-foreground">Any number</span>
              )
            ) : agent.agent_number ? (
              phone(agent.agent_number)
            ) : (
              none
            )}
          </Fact>
        )}
        <Fact label="Source">{SOURCE_NAMES[agent.source]}</Fact>
        <Fact label="External id" wrap>
          {agent.external_id ?? none}
        </Fact>
        <Fact label="Agent id">
          <CopyId id={agent.id} label="agent id" />
        </Fact>
        <Fact label="Added">{when(agent.created_at)}</Fact>
      </dl>
      <details className="group px-5 pt-3 pb-4">
        <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded-sm text-xs-500 text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
          <span className="group-open:hidden">Show more</span>
          <span className="hidden group-open:inline">Show less</span>
          <ChevronDown className="size-3.5 transition-transform duration-150 group-open:rotate-180" />
        </summary>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4">
          <Fact label="Languages">{languageNames(agent.languages)}</Fact>
          <Fact label="Opens with">
            {agent.agent_speaks_first ? "Agent speaks first" : "Caller speaks first"}
          </Fact>
          {outbound && <OutboundFacts outbound={outbound} />}
          {endpoint && (
            <Fact label="Headers" wrap>
              {endpoint.headers.length > 0
                ? endpoint.headers.map((header) => header.name).join(", ")
                : none}
            </Fact>
          )}
        </dl>
      </details>
    </Panel>
  );
}

/** What Yaksh sends to start an outbound agent's call, and how long it waits for the call. */
function OutboundFacts({ outbound }: { outbound: OutboundSettings }) {
  const { trigger } = outbound;
  return (
    <>
      <div className="col-span-full grid gap-0.5">
        <dt className="text-xs-400 text-muted-foreground">Start request</dt>
        <dd className="text-p-400 break-all">
          <span className="text-muted-foreground">POST </span>
          {trigger.url}
        </dd>
      </div>
      <Fact label="Headers" wrap>
        {trigger.headers.length > 0 ? (
          trigger.headers.map((header) => header.name).join(", ")
        ) : (
          <span className="font-normal text-muted-foreground">None</span>
        )}
      </Fact>
      <div className="col-span-full grid min-w-0 gap-1">
        <dt className="text-xs-400 text-muted-foreground">Request body</dt>
        <dd className="min-w-0">
          <pre className="max-h-48 overflow-auto rounded-md bg-muted p-3 font-mono text-xs-400 leading-relaxed">
            {JSON.stringify(trigger.body, null, 2)}
          </pre>
        </dd>
      </div>
      <Fact label="Dial window">{outbound.dial_window_s} seconds</Fact>
    </>
  );
}
