import { useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import {
  Fragment,
  memo,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useDefaultLayout } from "react-resizable-panels";
import { Link, useParams, useSearchParams } from "react-router";

import { ToolCalls } from "@/components/tool-calls";
import { AgentRecordPanel } from "@/components/agent-record";
import { CallMetricsCard } from "@/components/call-metrics";
import { CallResults } from "@/components/call-results";
import { CallSounds } from "@/components/call-sounds";
import { EndCallDialog } from "@/components/confirm-dialogs";
import { CopyId } from "@/components/copy-id";
import { Fact } from "@/components/panel";
import type { PlayerHandle } from "@/components/recording-player";
import { ResponseTime } from "@/components/response-time";
import { ConversationStatusLabel } from "@/components/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Message, MessageContent, MessageHeader } from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
  useMessageScroller,
} from "@/components/ui/message-scroller";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { AudioCard } from "@/components/audio-card";
import {
  type CallMoment,
  answeredText,
  callMoments,
  machineSpeaker,
  playsScenario,
  voicemailFacts,
} from "@/lib/answering";
import { playedDataSet } from "@/lib/data-sets";
import { copyText } from "@/lib/clipboard";
import { clock, duration, surroundingsLabel, phone, when, words } from "@/lib/format";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useStoredBoolean } from "@/hooks/use-stored-boolean";
import { APPEAR, REVEAL, RISE } from "@/lib/motion";
import { keys, useAgent, useConversation } from "@/lib/queries";
import { connectedAt, turnStart } from "@/lib/turns";
import { subscribe } from "@/lib/sse";
import { storage } from "@/lib/storage";
import { cn } from "@/lib/utils";
import {
  END_REASON_LABELS,
  ACTIVE_STATUSES,
  type Conversation,
  type EvaluationState,
  type Fact as ScenarioFact,
  LANGUAGE_NAMES,
  type PlayedScenario,
  type Turn,
  WIRE_EVENT_HELP,
  type WireEvent,
} from "@/lib/types";

/** Keyed by the conversation, so moving to another attempt starts with no turn shown and the
 * result rows opened for that call. */
export function ConversationPage() {
  const { id = "" } = useParams();
  return <ConversationView key={id} id={id} />;
}

function ConversationView({ id }: { id: string }) {
  const [params] = useSearchParams();
  const conversation = useConversation(id);
  const agent = useAgent(conversation.data?.agent_id);
  const [ending, setEnding] = useState(false);
  /** The turn a quote asked to see. */
  const [shown, setShown] = useState<ShownTurn | null>(null);
  const player = useRef<PlayerHandle>(null);
  const layout = useDefaultLayout({
    id: "yaksh.conversation",
    storage,
    onlySaveAfterUserInteractions: true,
  });
  useLiveUpdates(id, conversation.data?.status);

  if (conversation.isPending) {
    return (
      <div className="flex h-full flex-col gap-6">
        <Skeleton className="h-28 w-full" />
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_320px] gap-4">
          <Skeleton className="h-full" />
          <Skeleton className="h-full" />
        </div>
      </div>
    );
  }
  if (conversation.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the conversation</AlertTitle>
        <AlertDescription>{conversation.error.message}</AlertDescription>
      </Alert>
    );
  }
  const data = conversation.data;
  const active = ACTIVE_STATUSES.includes(data.status);
  const connectedMs = connectedAt(data);
  const showTurn = (turn: number) => {
    setShown({ index: turn - 1 });
    const at = turnStart(data, turn);
    if (data.recording_url && at !== null) player.current?.playFrom(at);
  };

  return (
    <div className="flex h-full flex-col gap-6">
      <div className="grid shrink-0 gap-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="grid min-w-0 gap-1">
            <h1 className="truncate text-h3-500" title={data.scenario_name}>
              {data.scenario_name}
            </h1>
            <p className="truncate text-s-400 text-muted-foreground">
              <Link
                to={`/agents/${data.agent_id}`}
                className="underline decoration-muted-foreground/40 underline-offset-4 hover:text-foreground hover:decoration-foreground"
              >
                {agent.data?.name ?? data.agent_name}
              </Link>
              , version {data.agent_version}, {data.persona_name}
              {playedDataSet(data) && ` · ${playedDataSet(data)}`}
            </p>
          </div>
          <div className="grid justify-items-end gap-1">
            <div className="flex items-center gap-4">
              <ConversationStatusLabel status={data.status} />
              {active && (
                <Button variant="outline" size="sm" onClick={() => setEnding(true)}>
                  End
                </Button>
              )}
              <EndCallDialog conversation={data} open={ending} onOpenChange={setEnding} />
            </div>
            <ConversationIds conversation={data} />
          </div>
        </div>
        <ConversationFacts key={data.id} conversation={data} />
        {data.failure_reason && (
          <p className="text-s-400 text-status-danger">{data.failure_reason}</p>
        )}
        {data.caller_reason && data.answered_by === "caller" && (
          <p className="text-s-400 text-muted-foreground">
            Why the caller hung up: {data.caller_reason}
          </p>
        )}
      </div>

      <ResizablePanelGroup
        orientation="horizontal"
        className="min-h-0 flex-1"
        defaultLayout={layout.defaultLayout}
        onLayoutChanged={layout.onLayoutChanged}
      >
        <ResizablePanel id="call" minSize="20%">
          <CallPane
            key={data.id}
            conversation={data}
            player={player}
            start={Number(params.get("t")) || 0}
            shown={shown}
          />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id="details" defaultSize={500} minSize={300} maxSize="80%">
          <Tabs
            defaultValue={data.evaluation ? "results" : "scenario"}
            className="h-full min-h-0 gap-3 pl-3"
          >
            <TabsList variant="line" className="shrink-0 overflow-x-auto overflow-y-hidden">
              <TabsTrigger value="results">Results</TabsTrigger>
              {data.agent_record && <TabsTrigger value="record">Agent record</TabsTrigger>}
              <TabsTrigger value="metrics">Metrics</TabsTrigger>
              <TabsTrigger value="scenario">Scenario</TabsTrigger>
              <TabsTrigger value="caller">Caller</TabsTrigger>
              <TabsTrigger value="events">Events</TabsTrigger>
            </TabsList>
            <ScrollArea className="min-h-0 flex-1">
              <div className="p-px pr-4 pb-6">
                <TabsContent value="results">
                  <CallResults
                    conversationId={data.id}
                    evaluation={data.evaluation}
                    onTurn={showTurn}
                    notPlayed={
                      playsScenario(data.answered_by, data.wire_events)
                        ? null
                        : `${data.answered_by === "voicemail" ? "A voicemail" : "A call screener"} answered, so no caller talked.`
                    }
                  />
                </TabsContent>
                {data.agent_record && (
                  <TabsContent value="record">
                    <AgentRecordPanel
                      conversationId={data.id}
                      status={data.agent_record}
                      evaluation={data.evaluation}
                      connectedMs={connectedMs}
                      onTurn={showTurn}
                    />
                  </TabsContent>
                )}
                <TabsContent value="metrics">
                  <CallMetricsCard conversationId={data.id} evaluation={data.evaluation} />
                </TabsContent>
                <TabsContent value="scenario">
                  <ScenarioCard
                    name={data.scenario_name}
                    scenario={data.scenario}
                    dataSet={playedDataSet(data)}
                  />
                </TabsContent>
                <TabsContent value="caller">
                  <Card>
                    <CardHeader>
                      <RailTitle role="Caller" name={data.persona_name} />
                      <CardDescription>
                        {LANGUAGE_NAMES[data.language]}, <CallerLine conversation={data} />, up to{" "}
                        {data.max_turns} turns and {data.max_duration_s}s once connected
                      </CardDescription>
                      {surroundingsLabel(data.surroundings) && (
                        <CardDescription>
                          Surroundings: {surroundingsLabel(data.surroundings)}
                        </CardDescription>
                      )}
                    </CardHeader>
                    <CardContent className="grid gap-3 text-p-400">
                      <CallerPrompt instructions={data.instructions} />
                    </CardContent>
                  </Card>
                  <CallSounds
                    sounds={data.sounds}
                    lengthS={data.talk_ms ? data.talk_ms / 1000 : data.max_duration_s}
                  />
                </TabsContent>
                <TabsContent value="events">
                  <WireEvents
                    events={data.wire_events}
                    validity={data.validity}
                    onPlay={
                      data.recording_url && connectedMs !== undefined
                        ? (atMs) => player.current?.playFrom(Math.max(0, atMs - connectedMs) / 1000)
                        : undefined
                    }
                  />
                </TabsContent>
              </div>
            </ScrollArea>
          </Tabs>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}

/** What is known about the call, as label and value pairs. A value that does not exist yet is
 * left out, not shown as empty. */
function ConversationFacts({ conversation }: { conversation: Conversation }) {
  const { latency } = conversation;
  const finished = !ACTIVE_STATUSES.includes(conversation.status);
  const [initial] = useState(conversation.status);
  const arrived = conversation.status === initial ? undefined : APPEAR;
  const answered = conversation.answered_by !== "caller";
  const persona = playsScenario(conversation.answered_by, conversation.wire_events);
  const voicemail = answered
    ? voicemailFacts(conversation.transcript, conversation.wire_events)
    : null;
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-3">
      {conversation.started_at && (
        <Fact className={arrived} label="Started">
          <span className="tabular-nums">{when(conversation.started_at)}</span>
        </Fact>
      )}
      {conversation.talk_ms !== null && (
        <Fact className={arrived} label="Connected">
          <span className="tabular-nums">{duration(conversation.talk_ms)}</span>
        </Fact>
      )}
      {answered && (
        <Fact label="Answered by">
          {answeredText(
            conversation.answered_by,
            conversation.answering,
            conversation.transcript,
            conversation.wire_events,
          )}
        </Fact>
      )}
      {conversation.end_reason && (
        <Fact className={arrived} label="End">
          {END_REASON_LABELS[conversation.end_reason]}
        </Fact>
      )}
      {voicemail && finished && (
        <>
          <Fact className={arrived} label="Talked over the greeting">
            {voicemail.talkedOver ? "Yes" : "No"}
          </Fact>
          <Fact className={arrived} label="Message">
            <span className="tabular-nums">{duration(voicemail.messageMs)}</span>
          </Fact>
        </>
      )}
      {!persona && finished && conversation.talk_ms !== null && (
        <Fact className={arrived} label="Response time">
          No caller turns
        </Fact>
      )}
      {persona && latency && (latency.p50_ms != null || latency.p90_ms != null) && (
        <Fact className={arrived} label="Response p50 / p90">
          <span className="flex items-center gap-1.5">
            {latency.p50_ms != null ? <ResponseTime ms={latency.p50_ms} /> : "–"}
            <span className="text-muted-foreground">/</span>
            {latency.p90_ms != null ? <ResponseTime ms={latency.p90_ms} /> : "–"}
          </span>
        </Fact>
      )}
      {persona && latency && (
        <Fact className={arrived} label="Replies">
          <span className="tabular-nums">{latency.replies}</span>
          {latency.talked_over > 0 && `, ${latency.talked_over} talked over`}
        </Fact>
      )}
      {persona && latency === null && finished && conversation.talk_ms !== null && (
        <Fact className={arrived} label="Response time">
          {measuring[conversation.evaluation ?? "none"]}
        </Fact>
      )}
      <Fact className={arrived} label="Run">
        <span className="flex gap-3">
          <Link to={`/runs/${conversation.run_id}`} className="underline-offset-4 hover:underline">
            Repeat {conversation.repeat}
          </Link>
          {(conversation.retry_of || conversation.retried_as) && (
            <span className="tabular-nums">Attempt {conversation.attempt}</span>
          )}
          {conversation.retry_of && (
            <Link
              to={`/conversations/${conversation.retry_of}`}
              className="underline-offset-4 hover:underline"
            >
              Previous attempt
            </Link>
          )}
          {conversation.retried_as && (
            <Link
              to={`/conversations/${conversation.retried_as}`}
              className="underline-offset-4 hover:underline"
            >
              Next attempt
            </Link>
          )}
        </span>
      </Fact>
    </dl>
  );
}

/** The ids to copy for the API, the CLI or a Plivo log search, in one quiet line. */
function ConversationIds({ conversation }: { conversation: Conversation }) {
  const session = agentSession(conversation);
  return (
    <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1 text-xs-400 text-muted-foreground">
      <span className="flex items-center gap-1.5">
        Conversation
        <CopyId id={conversation.id} label="conversation id" />
      </span>
      {conversation.call_uuid && (
        <span className="flex items-center gap-1.5">
          Plivo call
          <CopyId id={conversation.call_uuid} label="Plivo call id" />
        </span>
      )}
      {session && (
        <span className="flex items-center gap-1.5">
          Agent session
          <CopyId id={session} label="agent session id" />
        </span>
      )}
    </div>
  );
}

const measuring: Record<EvaluationState | "none", string> = {
  queued: "Measuring",
  running: "Measuring",
  failed: "Measurement failed",
  done: "Not measured",
  none: "Not measured",
};

/** A turn to bring into view, by index. Each ask is a new object, so asking for the same turn
 * again scrolls to it again. */
export interface ShownTurn {
  index: number;
}

/** The recording and the transcript. Keyed by the conversation, so the turn that was playing
 * does not carry over to the next conversation. */
export function CallPane({
  conversation,
  player,
  start,
  shown = null,
}: {
  conversation: Conversation;
  player: RefObject<PlayerHandle | null>;
  start: number;
  shown?: ShownTurn | null;
}) {
  const [heard, setHeard] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  const transcript = useRef<HTMLDivElement | null>(null);
  const slide = useRef<Animation | null>(null);
  /** Where the transcript was drawn when the player's size was asked to change. */
  const slideFrom = useRef<number | null>(null);
  const connectedMs = connectedAt(conversation);
  const overText = conversation.transport === "text";
  const toggle = useCallback(() => {
    slideFrom.current = transcript.current?.getBoundingClientRect().top ?? null;
    setExpanded((value) => !value);
  }, []);
  // The new size moves the transcript at once; it slides there from where it was drawn, also
  // when a slide is still running.
  useLayoutEffect(() => {
    const card = transcript.current;
    const from = slideFrom.current;
    slideFrom.current = null;
    if (!card || from === null) return;
    slide.current?.cancel();
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    slide.current = card.animate(
      [
        { transform: `translateY(${from - card.getBoundingClientRect().top}px)` },
        { transform: "translateY(0)" },
      ],
      // Chrome can start the slide a moment after this frame; "backwards" holds its first
      // position until then, so no frame shows the transcript at its end place too early.
      { duration: 240, easing: "cubic-bezier(0.2, 0, 0, 1)", fill: "backwards" },
    );
  }, [expanded]);
  const play = useCallback((seconds: number) => player.current?.playFrom(seconds), [player]);
  const moments = useMemo(
    () => (connectedMs === undefined ? [] : callMoments(conversation, connectedMs)),
    [conversation, connectedMs],
  );
  return (
    <div className="flex h-full flex-col gap-6 p-px pr-3">
      {!overText && (
        <AudioCard
          conversation={conversation}
          player={player}
          start={start}
          onTime={(seconds) => setHeard(turnAt(conversation.transcript, connectedMs ?? 0, seconds))}
          expanded={expanded}
          onToggle={toggle}
        />
      )}
      <Transcript
        cardRef={transcript}
        turns={conversation.transcript}
        moments={moments}
        active={ACTIVE_STATUSES.includes(conversation.status)}
        waiting={waitingText(conversation)}
        connectedMs={connectedMs ?? 0}
        heard={heard}
        shown={shown}
        onPlay={conversation.recording_url && connectedMs !== undefined ? play : undefined}
      />
    </div>
  );
}

/** The session id a text agent made for this conversation, from its first reply. */
function agentSession(conversation: Conversation): string | null {
  if (conversation.transport !== "text") return null;
  return conversation.wire_events.find((event) => event.kind === "connected")?.detail ?? null;
}

function CallerLine({ conversation }: { conversation: Conversation }) {
  if (conversation.transport === "text") return <>over text, with no phone call</>;
  const number = conversation.caller_number ?? "a number assigned at call time";
  if (conversation.direction === "inbound") return <>from {number}</>;
  return (
    <>
      answers on {number}
      {conversation.agent_caller_id && `, called from ${conversation.agent_caller_id}`}
    </>
  );
}

function waitingText(conversation: Conversation): string {
  const kinds = conversation.wire_events.map((event) => event.kind);
  if (!kinds.includes("waiting_for_call") || kinds.includes("answered")) {
    return "Waiting for the first words.";
  }
  return conversation.caller_number
    ? `Waiting for the agent to call ${phone(conversation.caller_number)}.`
    : "Waiting for the agent to call.";
}

function RailTitle({ role, name }: { role: string; name: string }) {
  return (
    <div className="grid gap-0.5">
      <span className="text-xs-400 text-muted-foreground">{role}</span>
      <CardTitle>{name}</CardTitle>
    </div>
  );
}

/** The scenario as the call played it: the instructions and criteria with the values of the
 * data set filled in, and that data set's facts. */
export function ScenarioCard({
  name,
  scenario,
  dataSet,
}: {
  name: string;
  scenario: PlayedScenario;
  /** The data set's name, when the scenario version held more than one. */
  dataSet: string | null;
}) {
  return (
    <Card>
      <CardHeader>
        <RailTitle role="Scenario" name={name} />
        <CardDescription className="whitespace-pre-wrap">{scenario.instructions}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 text-p-400">
          {dataSet && (
            <div className="grid gap-1">
              <dt className="text-xs-400 text-muted-foreground">Data set</dt>
              <dd>{dataSet}</dd>
            </div>
          )}
          {scenario.first_words && (
            <div className="grid gap-1">
              <dt className="text-xs-400 text-muted-foreground">First words</dt>
              <dd>{scenario.first_words}</dd>
            </div>
          )}
          <Facts label="Knows" facts={scenario.known_facts} />
          <Facts label="Sent to the agent" facts={scenario.agent_data} />
          {scenario.unknown_facts.length > 0 && (
            <div className="grid gap-1">
              <dt className="text-xs-400 text-muted-foreground">Does not have</dt>
              <dd>{scenario.unknown_facts.join(", ")}</dd>
            </div>
          )}
          <div className="grid gap-1">
            <dt className="text-xs-400 text-muted-foreground">Criteria</dt>
            <dd>
              <ul className="grid list-disc gap-1 pl-4 marker:text-muted-foreground">
                {scenario.criteria.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function Facts({ label, facts }: { label: string; facts: ScenarioFact[] }) {
  if (facts.length === 0) return null;
  return (
    <div className="grid gap-1">
      <dt className="text-xs-400 text-muted-foreground">{label}</dt>
      <dd className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
        {facts.map((fact) => (
          <Fragment key={fact.name}>
            <span className="text-muted-foreground">{fact.name}</span>
            <span className="font-medium break-words">{fact.value}</span>
          </Fragment>
        ))}
      </dd>
    </div>
  );
}

function CallerPrompt({ instructions }: { instructions: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="grid gap-2">
      <Button
        variant="link"
        size="sm"
        className="h-auto justify-self-start p-0"
        aria-expanded={shown}
        onClick={() => setShown(!shown)}
      >
        {shown ? "Hide prompt" : "Show prompt"}
      </Button>
      {shown && (
        <pre
          className={cn(
            "whitespace-pre-wrap rounded-md bg-muted p-3 font-mono text-xs-400",
            REVEAL,
          )}
        >
          {instructions}
        </pre>
      )}
    </div>
  );
}

function useLiveUpdates(id: string, status: Conversation["status"] | undefined) {
  const client = useQueryClient();
  const live = status !== undefined && ACTIVE_STATUSES.includes(status);
  useEffect(() => {
    if (!live) return;
    const controller = new AbortController();
    const key = keys.conversation(id);
    const patch = (update: (current: Conversation) => Conversation) =>
      client.setQueryData<Conversation>(key, (current) => (current ? update(current) : current));
    const finished = () => {
      const current = client.getQueryData<Conversation>(key);
      return current !== undefined && !ACTIVE_STATUSES.includes(current.status);
    };
    void (async () => {
      let delay = 1_000;
      while (!controller.signal.aborted) {
        // The stream replays from the first turn on every connection; events are applied by
        // index so a replay overwrites what the snapshot already showed instead of duplicating it.
        const seen = { turns: 0, events: 0 };
        try {
          await subscribe(
            `/conversations/${id}/events`,
            ({ event, data }) => {
              const payload = JSON.parse(data);
              if (event === "turn") {
                const index = seen.turns++;
                patch((current) => ({
                  ...current,
                  transcript: place(current.transcript, index, payload),
                }));
              } else if (event === "wire_event") {
                const index = seen.events++;
                patch((current) => ({
                  ...current,
                  wire_events: place(current.wire_events, index, payload),
                }));
                // The number is leased after the status turns running, so the snapshot fetched
                // on that status change can come back without it.
                if (
                  payload.kind === "waiting_for_call" &&
                  !client.getQueryData<Conversation>(key)?.caller_number
                ) {
                  void client.invalidateQueries({ queryKey: key });
                }
              } else if (event === "status") {
                patch((current) => ({ ...current, status: payload.status }));
                void client.invalidateQueries({ queryKey: ["conversations"], exact: false });
              }
            },
            controller.signal,
          );
          delay = 1_000;
        } catch {
          if (controller.signal.aborted) return;
        }
        if (controller.signal.aborted) return;
        await client.invalidateQueries({ queryKey: key });
        if (finished()) return;
        await pause(delay, controller.signal);
        delay = Math.min(delay * 2, 5_000);
      }
    })();
    return () => controller.abort();
  }, [client, id, live]);
}

function place<T>(list: T[], index: number, item: T): T[] {
  const next = list.slice(0, Math.max(list.length, index));
  next[index] = item;
  return next;
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal.addEventListener("abort", done);
  });
}

/** The turn the recording plays at that second: the last one to start by then. */
function turnAt(turns: Turn[], connectedMs: number, seconds: number): number | null {
  const now = connectedMs + seconds * 1000;
  let found: number | null = null;
  turns.forEach((turn, index) => {
    if (
      turn.started_at_ms <= now &&
      (found === null || turn.started_at_ms >= turns[found].started_at_ms)
    ) {
      found = index;
    }
  });
  return found;
}

/** Keeps the turn the recording plays in view. */
function FollowAudio({ index }: { index: number | null }) {
  const { scrollToMessage } = useMessageScroller();
  useEffect(() => {
    if (index === null) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scrollToMessage(String(index), { align: "center", behavior: still ? "auto" : "smooth" });
  }, [index, scrollToMessage]);
  return null;
}

/** Brings the turn a quote asked for into view. */
function ShowTurn({ shown }: { shown: ShownTurn | null }) {
  const { scrollToMessage } = useMessageScroller();
  useEffect(() => {
    if (shown === null) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scrollToMessage(String(shown.index), { align: "center", behavior: still ? "auto" : "smooth" });
  }, [shown, scrollToMessage]);
  return null;
}

const Transcript = memo(function Transcript({
  turns,
  moments,
  active,
  waiting,
  connectedMs,
  heard,
  shown,
  onPlay,
  cardRef,
}: {
  turns: Turn[];
  /** Lines between the turns, by time. */
  moments: CallMoment[];
  active: boolean;
  waiting: string;
  /** Turn times count from the dial; they show from the connect, as the recording does. */
  connectedMs: number;
  /** The turn the recording is playing, by index. */
  heard: number | null;
  /** The turn a quote asked to see. */
  shown: ShownTurn | null;
  /** Plays the recording from that second; absent while there is no recording. */
  onPlay?: (seconds: number) => void;
  /** The card, which slides when the player above it changes size. */
  cardRef: RefObject<HTMLDivElement | null>;
}) {
  const [follow, setFollow] = useStoredBoolean("yaksh.transcript.follow", true);
  /** A live call opens at its newest turn, a finished one at its first. Kept from the first
   * render, so a call that ends while it is open does not jump back to the start. */
  const [openedLive] = useState(active);
  return (
    <Card ref={cardRef} className="relative z-10 min-h-0">
      <CardHeader className="shrink-0 border-b">
        <CardTitle>Transcript</CardTitle>
        {onPlay && (
          <CardAction>
            <label className="flex items-center gap-2 text-p-400 text-muted-foreground">
              <Switch checked={follow} onCheckedChange={setFollow} />
              Follow audio
            </label>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="min-h-0 flex-1">
        {turns.length === 0 ? (
          <p className="text-p-400 text-muted-foreground">
            {active ? waiting : "Nothing was transcribed."}
          </p>
        ) : (
          <MessageScrollerProvider
            autoScroll={active}
            defaultScrollPosition={openedLive ? "end" : "start"}
          >
            <MessageScroller>
              {onPlay && <FollowAudio index={follow ? heard : null} />}
              <ShowTurn shown={shown} />
              <MessageScrollerViewport className="pr-4">
                <MessageScrollerContent className="gap-4">
                  {timeline(turns, moments).map((line) => {
                    if (line.kind === "moment") {
                      return (
                        <MomentRow
                          key={`${line.moment.at_ms}-${line.moment.text}`}
                          moment={line.moment}
                          connectedMs={connectedMs}
                        />
                      );
                    }
                    const { turn, index } = line;
                    const at = Math.max(0, turn.started_at_ms - connectedMs);
                    return (
                      <MessageScrollerItem
                        key={index}
                        messageId={String(index)}
                        className={active ? RISE : undefined}
                      >
                        <Message align={turn.role === "caller" ? "end" : "start"}>
                          <MessageContent>
                            <MessageHeader className="gap-2 tabular-nums">
                              <span
                                className={turn.machine ? "font-medium text-secondary" : undefined}
                              >
                                {turn.machine
                                  ? machineSpeaker(turn.machine)
                                  : turn.role === "agent"
                                    ? "Agent"
                                    : "Caller"}
                              </span>
                              <span>{clock(at)}</span>
                              {typeof turn.response_ms === "number" && (
                                <ResponseTime ms={turn.response_ms} />
                              )}
                              {turn.talked_over && <Badge>Talked over</Badge>}
                              {turn.scripted && <Badge>Fixed line</Badge>}
                              {turn.dtmf && <Badge>DTMF</Badge>}
                              {turn.provenance === "cut" && <Badge>Cut off</Badge>}
                              {turn.provenance === "unconfirmed" && (
                                <Badge>Not confirmed played</Badge>
                              )}
                              <button
                                type="button"
                                title={`Copy turn ${index + 1}`}
                                aria-label={`Copy turn ${index + 1}`}
                                onClick={() => void copyText(turn.text, "Message copied")}
                                className="-m-0.5 rounded-sm p-0.5 opacity-0 outline-none transition-[color,opacity] group-hover/message:opacity-100 group-data-[align=end]/message:order-first hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
                              >
                                <Copy className="size-3.5" />
                              </button>
                            </MessageHeader>
                            <Bubble variant={turn.machine ? "outline" : turn.role}>
                              <BubbleContent
                                render={
                                  onPlay && (
                                    <button
                                      type="button"
                                      title="Play from here"
                                      onClick={() => onPlay(at / 1000)}
                                    />
                                  )
                                }
                                className={cn(
                                  onPlay && "cursor-pointer",
                                  index === heard && "ring-2 ring-ring/60",
                                  index === shown?.index && "ring-2 ring-status-progress/70",
                                  turn.provenance === "cut" && "line-through opacity-60",
                                  turn.provenance === "unconfirmed" && "opacity-60",
                                  turn.machine && "border-dashed text-muted-foreground",
                                )}
                              >
                                {turn.text}
                              </BubbleContent>
                            </Bubble>
                            {turn.tools?.length > 0 && <ToolCalls tools={turn.tools} />}
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    );
                  })}
                  {active && (
                    <p className="flex items-center gap-2 text-xs-400 text-muted-foreground">
                      <Spinner className="size-3" />
                      Live
                    </p>
                  )}
                </MessageScrollerContent>
              </MessageScrollerViewport>
              <MessageScrollerButton />
            </MessageScroller>
          </MessageScrollerProvider>
        )}
      </CardContent>
    </Card>
  );
});

type TranscriptLine =
  | { kind: "turn"; turn: Turn; index: number }
  | { kind: "moment"; moment: CallMoment };

/** The turns in transcript order, which the judges' turn numbers follow, with each moment
 * before the first of them that starts at or after it. A turn keeps its index, which the
 * recording and the quotes use. */
function timeline(turns: Turn[], moments: CallMoment[]): TranscriptLine[] {
  const sorted = [...moments].sort((a, b) => a.at_ms - b.at_ms);
  const lines: TranscriptLine[] = [];
  let next = 0;
  turns.forEach((turn, index) => {
    for (; next < sorted.length && sorted[next].at_ms <= turn.started_at_ms; next++) {
      lines.push({ kind: "moment", moment: sorted[next] });
    }
    lines.push({ kind: "turn", turn, index });
  });
  return [...lines, ...sorted.slice(next).map((moment) => ({ kind: "moment" as const, moment }))];
}

function MomentRow({ moment, connectedMs }: { moment: CallMoment; connectedMs: number }) {
  return (
    <div
      role="separator"
      className="flex items-center gap-3 text-xs-400 text-muted-foreground tabular-nums before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border"
    >
      {moment.text} · {clock(Math.max(0, moment.at_ms - connectedMs))}
    </div>
  );
}

function WireEvents({
  events,
  validity,
  onPlay,
}: {
  events: WireEvent[];
  validity: Conversation["validity"];
  /** Plays the recording from that time, counted from the dial; absent while there is no
   * recording. An event before the connect plays from the start. */
  onPlay?: (atMs: number) => void;
}) {
  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>Events</CardTitle>
        <CardDescription>
          Times count from the start of the call. The recording and the transcript start at
          connected.
        </CardDescription>
        {validity && !validity.ok && (
          <CardDescription className="text-status-danger">
            {validity.reasons.join("; ")}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-p-400 text-muted-foreground">Nothing yet.</p>
        ) : (
          <ol className="grid gap-1 font-mono text-xs-400">
            {events.map((event, index) => (
              <li key={index} className="grid gap-0.5">
                <div className="flex justify-between gap-4">
                  <Tooltip>
                    <TooltipTrigger
                      className={cn(
                        "cursor-help rounded-sm underline decoration-dotted underline-offset-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                        event.kind === "caller_error" && "text-status-danger",
                      )}
                    >
                      {words(event.kind)}
                    </TooltipTrigger>
                    <TooltipContent side="left">{WIRE_EVENT_HELP[event.kind]}</TooltipContent>
                  </Tooltip>
                  {onPlay ? (
                    <button
                      type="button"
                      title="Play from here"
                      onClick={() => onPlay(event.at_ms)}
                      className="rounded-sm text-muted-foreground underline-offset-2 outline-none transition-colors hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                    >
                      {clock(event.at_ms)}
                    </button>
                  ) : (
                    <span className="text-muted-foreground">{clock(event.at_ms)}</span>
                  )}
                </div>
                {event.detail && <p className="break-all text-muted-foreground">{event.detail}</p>}
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
