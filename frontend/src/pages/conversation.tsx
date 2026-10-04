import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import { Link, useParams, useSearchParams } from "react-router";

import { type Mark, type PlayerHandle, RecordingPlayer } from "@/components/recording-player";
import { ResponseTime } from "@/components/response-time";
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
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { cn } from "cn";

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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  BAND_FILL,
  BAND_TEXT,
  clock,
  counted,
  duration,
  noiseLabel,
  phone,
  responseBand,
  seconds,
  when,
  words,
} from "@/lib/format";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useStoredBoolean } from "@/hooks/use-stored-boolean";
import { keys, useAgent, useConversation, useEndConversation } from "@/lib/queries";
import { subscribe } from "@/lib/sse";
import { storage } from "@/lib/storage";
import {
  END_REASON_LABELS,
  ACTIVE_STATUSES,
  type Conversation,
  type Fact,
  LANGUAGE_NAMES,
  type Reply,
  type ScenarioConfig,
  type Turn,
  WIRE_EVENT_HELP,
  type WireEvent,
} from "@/lib/types";

export function ConversationPage() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const conversation = useConversation(id);
  const agent = useAgent(conversation.data?.agent_id);
  const end = useEndConversation(id);
  const layout = useDefaultLayout({
    id: "truman.conversation",
    storage,
    onlySaveAfterUserInteractions: true,
  });
  useLiveUpdates(id, conversation.data?.status);

  if (conversation.isPending) return <Skeleton className="h-96 w-full" />;
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

  return (
    <div className="flex h-full flex-col gap-6">
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-4">
        <div className="grid gap-1.5">
          <div className="flex items-center gap-3">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">
              {agent.data ? (
                <Link to={`/agents/${agent.data.id}`} className="hover:underline">
                  {agent.data.name}
                </Link>
              ) : (
                "Conversation"
              )}
            </h1>
            <StatusBadge status={data.status} />
          </div>
          <p className="text-sm text-muted-foreground">
            Version {data.agent_version}
            {data.started_at && ` · started ${when(data.started_at)}`}
            {data.talk_ms !== null && ` · ${duration(data.talk_ms)} connected`}
            {data.end_reason && ` · ${END_REASON_LABELS[data.end_reason]}`}
          </p>
          <LatencyLine conversation={data} />
          {data.failure_reason && (
            <p className="text-sm text-status-danger">{data.failure_reason}</p>
          )}
          {data.run_id && (
            <p className="flex flex-wrap gap-x-3 text-sm text-muted-foreground">
              <Link to={`/runs/${data.run_id}`} className="underline-offset-4 hover:underline">
                Repeat {data.repeat} of a run
              </Link>
              {data.retry_of && (
                <Link
                  to={`/conversations/${data.retry_of}`}
                  className="underline-offset-4 hover:underline"
                >
                  Attempt {data.attempt}, retry of attempt {data.attempt - 1}
                </Link>
              )}
              {data.retried_as && (
                <Link
                  to={`/conversations/${data.retried_as}`}
                  className="underline-offset-4 hover:underline"
                >
                  Retried as attempt {data.attempt + 1}
                </Link>
              )}
            </p>
          )}
          {data.caller_reason && (
            <p className="text-sm text-muted-foreground">
              Why the caller hung up: {data.caller_reason}
            </p>
          )}
        </div>
        {active && (
          <AlertDialog>
            <AlertDialogTrigger render={<Button variant="outline" />}>End call</AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>End this conversation?</AlertDialogTitle>
                <AlertDialogDescription>
                  {data.status === "queued"
                    ? "It has not connected yet, so it will be cancelled."
                    : "The caller hangs up and what was said so far is kept."}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep going</AlertDialogCancel>
                <AlertDialogAction onClick={() => end.mutate()}>End call</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>

      <ResizablePanelGroup
        orientation="horizontal"
        className="min-h-0 flex-1"
        defaultLayout={layout.defaultLayout}
        onLayoutChanged={layout.onLayoutChanged}
      >
        <ResizablePanel id="call" minSize="35%">
          <CallPane key={data.id} conversation={data} start={Number(params.get("t")) || 0} />
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id="details" defaultSize={320} minSize={260} maxSize="50%">
          <ScrollArea className="h-full">
            <div className="flex flex-col gap-6 p-px pr-4 pl-3">
              <ScenarioCard name={data.scenario_name} scenario={data.scenario} />
              <Card>
                <CardHeader>
                  <RailTitle role="Caller" name={data.persona_name} />
                  <CardDescription>
                    {LANGUAGE_NAMES[data.language]}, <CallerLine conversation={data} />, up to{" "}
                    {data.max_turns} turns and {data.max_duration_s}s once connected
                    {data.call_uuid && (
                      <>
                        {" · Plivo call "}
                        <span className="font-mono">{data.call_uuid}</span>
                      </>
                    )}
                  </CardDescription>
                  {noiseLabel(data.background_noise) && (
                    <CardDescription>
                      Background noise: {noiseLabel(data.background_noise)}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="grid gap-3 text-sm">
                  <CallerPrompt instructions={data.instructions} />
                </CardContent>
              </Card>
              <WireEvents events={data.wire_events} validity={data.validity} />
            </div>
          </ScrollArea>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}

/** The recording and the transcript. Keyed by the conversation, so the turn that was playing
 * does not carry over to the next conversation. */
/** The agent's response times, under the title; nothing during the call or for a call that did
 * not connect. */
function LatencyLine({ conversation }: { conversation: Conversation }) {
  const { latency } = conversation;
  if (latency === null) {
    if (conversation.talk_ms === null || ACTIVE_STATUSES.includes(conversation.status)) return null;
    return <p className="text-sm text-muted-foreground">Latency not measured</p>;
  }
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-muted-foreground">
      {latency.p90_ms !== null && latency.p50_ms !== null && (
        <>
          Response p90 <ResponseTime ms={latency.p90_ms} /> · p50{" "}
          <ResponseTime ms={latency.p50_ms} /> ·
        </>
      )}
      <span>
        {counted(latency.replies, "reply", "replies")}
        {latency.talked_over > 0 && ` · ${counted(latency.talked_over, "talk-over", "talk-overs")}`}
      </span>
    </p>
  );
}

/** One reply as a band on the waveform: the wait in its colour, or the overlap of a talk-over. */
function replyMark(reply: Reply, connectedMs: number): Mark {
  const from = (Math.min(reply.start_ms, reply.speech_ms) - connectedMs) / 1000;
  const to = (Math.max(reply.start_ms, reply.speech_ms) - connectedMs) / 1000;
  if (reply.speech_ms < reply.start_ms) {
    return {
      from,
      to,
      label: "talked over",
      title: `Agent started ${seconds(reply.start_ms - reply.speech_ms)} before the caller finished`,
      fill: "bg-foreground/10",
      text: "text-muted-foreground",
    };
  }
  const wait = reply.speech_ms - reply.start_ms;
  const band = responseBand(wait);
  return {
    from,
    to,
    label: seconds(wait),
    title: `Agent answered after ${seconds(wait)}`,
    fill: BAND_FILL[band],
    text: BAND_TEXT[band],
  };
}

function CallPane({ conversation, start }: { conversation: Conversation; start: number }) {
  const player = useRef<PlayerHandle>(null);
  const [heard, setHeard] = useState<number | null>(null);
  /** The recording starts when the call connects; turn times count from the dial. */
  const connectedMs = conversation.wire_events.find((event) => event.kind === "connected")?.at_ms;
  return (
    <div className="flex h-full flex-col gap-6 p-px pr-3">
      <Card className="shrink-0">
        <CardHeader>
          <CardTitle>Recording</CardTitle>
        </CardHeader>
        <CardContent>
          <RecordingPlayer
            ref={player}
            url={conversation.recording_url}
            name={`truman-${conversation.id}`}
            start={start}
            onTime={(seconds) =>
              setHeard(turnAt(conversation.transcript, connectedMs ?? 0, seconds))
            }
            marks={
              connectedMs === undefined
                ? []
                : conversation.replies.map((reply) => replyMark(reply, connectedMs))
            }
          />
        </CardContent>
      </Card>
      <Transcript
        turns={conversation.transcript}
        active={ACTIVE_STATUSES.includes(conversation.status)}
        waiting={waitingText(conversation)}
        connectedMs={connectedMs ?? 0}
        heard={heard}
        onPlay={
          conversation.recording_url && connectedMs !== undefined
            ? (seconds) => player.current?.playFrom(seconds)
            : undefined
        }
      />
    </div>
  );
}

function CallerLine({ conversation }: { conversation: Conversation }) {
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
      <span className="text-xs text-muted-foreground">{role}</span>
      <CardTitle>{name}</CardTitle>
    </div>
  );
}

function ScenarioCard({ name, scenario }: { name: string; scenario: ScenarioConfig }) {
  return (
    <Card>
      <CardHeader>
        <RailTitle role="Scenario" name={name} />
        <CardDescription className="whitespace-pre-wrap">{scenario.goal}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 text-sm">
          <Facts label="Knows" facts={scenario.known_facts} />
          <Facts label="Sent to the agent" facts={scenario.agent_data} />
          {scenario.unknown_facts.length > 0 && (
            <div className="grid gap-1">
              <dt className="text-xs text-muted-foreground">Does not have</dt>
              <dd>{scenario.unknown_facts.join(", ")}</dd>
            </div>
          )}
          <div className="grid gap-1">
            <dt className="text-xs text-muted-foreground">Criteria</dt>
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

function Facts({ label, facts }: { label: string; facts: Fact[] }) {
  if (facts.length === 0) return null;
  return (
    <div className="grid gap-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
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
        <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 font-mono text-xs transition-[opacity,translate] duration-200 ease-out starting:-translate-y-1 starting:opacity-0 motion-reduce:starting:translate-y-0">
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

function Transcript({
  turns,
  active,
  waiting,
  connectedMs,
  heard,
  onPlay,
}: {
  turns: Turn[];
  active: boolean;
  waiting: string;
  /** Turn times count from the dial; they show from the connect, as the recording does. */
  connectedMs: number;
  /** The turn the recording is playing, by index. */
  heard: number | null;
  /** Plays the recording from that second; absent while there is no recording. */
  onPlay?: (seconds: number) => void;
}) {
  const [follow, setFollow] = useStoredBoolean("truman.transcript.follow", true);
  return (
    <Card className="min-h-0">
      <CardHeader className="shrink-0">
        <CardTitle>Transcript</CardTitle>
        {onPlay && (
          <CardAction>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Switch checked={follow} onCheckedChange={setFollow} />
              Follow audio
            </label>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="min-h-0 flex-1">
        {turns.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {active ? waiting : "Nothing was transcribed."}
          </p>
        ) : (
          <MessageScrollerProvider autoScroll>
            <MessageScroller>
              {onPlay && <FollowAudio index={follow ? heard : null} />}
              <MessageScrollerViewport className="pr-4">
                <MessageScrollerContent className="gap-4">
                  {turns.map((turn, index) => {
                    const at = Math.max(0, turn.started_at_ms - connectedMs);
                    return (
                      <MessageScrollerItem
                        key={index}
                        messageId={String(index)}
                        className="transition-[opacity,translate] duration-200 ease-out starting:translate-y-1 starting:opacity-0 motion-reduce:starting:translate-y-0"
                      >
                        <Message align={turn.role === "caller" ? "end" : "start"}>
                          <MessageContent>
                            <MessageHeader className="gap-2 font-mono">
                              <span>{turn.role === "agent" ? "Agent" : "Caller"}</span>
                              <span>{clock(at)}</span>
                              {typeof turn.response_ms === "number" && (
                                <ResponseTime ms={turn.response_ms} />
                              )}
                              {turn.talked_over && <Badge variant="outline">talked over</Badge>}
                              {turn.scripted && <Badge variant="secondary">fixed nudge</Badge>}
                              {turn.provenance === "cut" && (
                                <Badge variant="outline">cut off</Badge>
                              )}
                              {turn.provenance === "unconfirmed" && (
                                <Badge variant="outline">not confirmed played</Badge>
                              )}
                            </MessageHeader>
                            <Bubble variant={turn.role === "caller" ? "default" : "outline"}>
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
                                  turn.provenance === "cut" && "line-through opacity-60",
                                  turn.provenance === "unconfirmed" && "opacity-60",
                                )}
                              >
                                {turn.text}
                              </BubbleContent>
                            </Bubble>
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    );
                  })}
                  {active && (
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
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
}

function WireEvents({
  events,
  validity,
}: {
  events: WireEvent[];
  validity: Conversation["validity"];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>On the wire</CardTitle>
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
          <p className="text-sm text-muted-foreground">Nothing yet.</p>
        ) : (
          <ol className="grid gap-1 font-mono text-xs">
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
                  <span className="text-muted-foreground">{clock(event.at_ms)}</span>
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
