import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { StatusBadge } from "@/components/status-badge";
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Message, MessageContent, MessageHeader } from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { UNAUTHORIZED_EVENT, authHeaders } from "@/lib/api";
import { clock, duration, when, words } from "@/lib/format";
import { keys, useAgent, useConversation, useEndConversation } from "@/lib/queries";
import { subscribe } from "@/lib/sse";
import { ACTIVE_STATUSES, type Conversation, type Turn, type WireEvent } from "@/lib/types";

export function ConversationPage() {
  const { id = "" } = useParams();
  const conversation = useConversation(id);
  const agent = useAgent(conversation.data?.agent_id);
  const end = useEndConversation(id);
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
    <div className="flex min-h-full flex-col gap-6 lg:h-full">
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
            {data.duration_ms !== null && ` · ${duration(data.duration_ms)}`}
            {data.end_reason && ` · ended by ${words(data.end_reason)}`}
          </p>
          {data.failure_reason && (
            <p className="text-sm text-status-danger">{data.failure_reason}</p>
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

      <div className="grid gap-6 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_20rem] lg:grid-rows-[minmax(0,1fr)]">
        <Transcript turns={data.transcript} active={active} />
        <ScrollArea className="lg:min-h-0">
          <div className="flex flex-col gap-6 p-px lg:pr-4">
            <Recording url={data.recording_url} />
            <Card>
              <CardHeader>
                <CardTitle>Persona</CardTitle>
                <CardDescription>
                  From {data.caller_number ?? "a number assigned at call time"}, up to{" "}
                  {data.max_duration_s}s
                  {data.call_uuid && (
                    <>
                      {" · Plivo call "}
                      <span className="font-mono">{data.call_uuid}</span>
                    </>
                  )}
                </CardDescription>
              </CardHeader>
              <CardContent className="whitespace-pre-wrap text-sm">
                {data.persona_prompt}
              </CardContent>
            </Card>
            <WireEvents events={data.wire_events} validity={data.validity} />
          </div>
        </ScrollArea>
      </div>
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

function Transcript({ turns, active }: { turns: Turn[]; active: boolean }) {
  return (
    <Card className="lg:min-h-0">
      <CardHeader className="shrink-0">
        <CardTitle>Transcript</CardTitle>
      </CardHeader>
      <CardContent className="lg:min-h-0 lg:flex-1">
        {turns.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {active ? "Waiting for the first words." : "Nothing was said."}
          </p>
        ) : (
          <MessageScrollerProvider autoScroll>
            <MessageScroller>
              <MessageScrollerViewport className="lg:pr-4">
                <MessageScrollerContent className="gap-4">
                  {turns.map((turn, index) => (
                    <MessageScrollerItem
                      key={index}
                      messageId={String(index)}
                      className="transition-[opacity,translate] duration-200 ease-out starting:translate-y-1 starting:opacity-0 motion-reduce:starting:translate-y-0"
                    >
                      <Message align={turn.role === "caller" ? "end" : "start"}>
                        <MessageContent>
                          <MessageHeader className="gap-2 font-mono">
                            <span>{turn.role === "agent" ? "Agent" : "Caller"}</span>
                            <span>{clock(turn.started_at_ms)}</span>
                            {turn.provenance === "cut" && <Badge variant="outline">cut off</Badge>}
                          </MessageHeader>
                          <Bubble variant={turn.role === "caller" ? "default" : "outline"}>
                            <BubbleContent
                              className={cn(turn.provenance === "cut" && "line-through opacity-60")}
                            >
                              {turn.text}
                            </BubbleContent>
                          </Bubble>
                        </MessageContent>
                      </Message>
                    </MessageScrollerItem>
                  ))}
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

function Recording({ url }: { url: string | null }) {
  const [blob, setBlob] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!url) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    fetch(url, { headers: authHeaders(), signal: controller.signal })
      .then((response) => {
        if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
        if (!response.ok) throw new Error(response.statusText);
        return response.blob();
      })
      .then((audio) => {
        objectUrl = URL.createObjectURL(audio);
        setBlob(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recording</CardTitle>
        <CardDescription>Agent on the left channel, caller on the right.</CardDescription>
      </CardHeader>
      <CardContent>
        {blob ? (
          <audio controls src={blob} className="w-full" />
        ) : (
          <p className="text-sm text-muted-foreground">
            {failed
              ? "The recording did not load. Reload the page to try again."
              : url
                ? "Loading."
                : "Available once the call has ended."}
          </p>
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
              <li key={index} className="flex justify-between gap-4">
                <span className={event.kind === "caller_error" ? "text-status-danger" : ""}>
                  {words(event.kind)}
                </span>
                <span className="text-muted-foreground">{clock(event.at_ms)}</span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
