import { ChevronDown, ChevronUp } from "lucide-react";
import { type ReactNode, type RefObject, useLayoutEffect, useRef } from "react";

import { type Mark, type PlayerHandle, RecordingPlayer } from "@/components/recording-player";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { LiveWaveform } from "@/components/waveform";
import { useLiveListen } from "@/hooks/use-live-listen";
import { machineBand, machineSpeaker, soundMs } from "@/lib/answering";
import { BAND_TEXT, BAND_WASH, clock, latency, responseBand } from "@/lib/format";
import type { LiveView } from "@/lib/listen";
import { connectedAt } from "@/lib/turns";
import { cn } from "@/lib/utils";
import { type Conversation, LIVE_STATUSES, type Reply } from "@/lib/types";

/** One reply as a band on the waveform: the wait in its colour, or the overlap of a talk-over. */
function replyMark(reply: Reply, connectedMs: number): Mark {
  const from = (Math.min(reply.start_ms, reply.speech_ms) - connectedMs) / 1000;
  const to = (Math.max(reply.start_ms, reply.speech_ms) - connectedMs) / 1000;
  if (reply.speech_ms < reply.start_ms) {
    return {
      from,
      to,
      label: "talked over",
      title: `Agent started ${latency(reply.start_ms - reply.speech_ms)} before the caller finished`,
      fill: "bg-foreground/10",
      text: "text-muted-foreground",
    };
  }
  const wait = reply.speech_ms - reply.start_ms;
  const band = responseBand(wait);
  return {
    from,
    to,
    label: latency(wait),
    title: `Agent answered after ${latency(wait)}`,
    fill: BAND_WASH[band],
    text: BAND_TEXT[band],
  };
}

const MACHINE_FILL: Record<string, { fill: string; text: string }> = {
  line: { fill: "bg-status-neutral/15", text: "text-muted-foreground" },
  tone: { fill: "bg-status-progress/15", text: "text-status-progress" },
  hold: { fill: "bg-status-warning/15", text: "text-status-warning-text" },
};

/** The persona's phone on the waveform: each recorded line, the voicemail's tone and the
 * screener's hold. */
function machineMarks(conversation: Conversation, connectedMs: number): Mark[] {
  const at = (ms: number) => Math.max(0, ms - connectedMs) / 1000;
  const end = conversation.talk_ms === null ? Infinity : conversation.talk_ms / 1000;
  const lines = conversation.transcript.flatMap((turn): Mark[] =>
    turn.machine
      ? [
          {
            from: at(turn.started_at_ms),
            to: at(turn.ended_at_ms),
            label: machineBand(turn.machine),
            title: `Recorded line of the ${machineSpeaker(turn.machine).toLowerCase()}`,
            ...MACHINE_FILL.line,
          },
        ]
      : [],
  );
  const sounds = conversation.wire_events.flatMap((event): Mark[] => {
    if (event.kind === "caller_sound") {
      return [
        {
          from: at(event.at_ms),
          to: at(event.at_ms + soundMs(event)),
          label: "Tone",
          title: "The voicemail's tone",
          ...MACHINE_FILL.tone,
        },
      ];
    }
    if (event.kind === "hold_started") {
      const hold = Number(event.detail ?? 0) / 1000;
      return [
        {
          from: at(event.at_ms),
          to: Math.min(at(event.at_ms) + hold, end),
          label: "Hold",
          title: `The call screener held the agent for ${Math.round(hold)} s`,
          ...MACHINE_FILL.hold,
        },
      ];
    }
    return [];
  });
  return [...lines, ...sounds];
}

/** The bands on the recording: the persona's phone and each reply's wait. */
function callMarks(conversation: Conversation): Mark[] {
  const connectedMs = connectedAt(conversation);
  if (connectedMs === undefined) return [];
  return [
    ...machineMarks(conversation, connectedMs),
    ...conversation.replies.map((reply) => replyMark(reply, connectedMs)),
  ];
}

/** The call's audio: while the call is live, a Listen button that plays it and draws it as it
 * plays; after the call, the recording. It holds the listening, so only this card redraws as
 * the audio plays. It opens small, with every control; Expand adds the ruler and taller lanes.
 * Listen and Stop listening are one button that keeps its place, so the focus stays on it. */
export function AudioCard({
  conversation,
  player,
  start,
  onTime,
  expanded,
  onToggle,
}: {
  conversation: Conversation;
  player: RefObject<PlayerHandle | null>;
  start: number;
  onTime: (seconds: number) => void;
  expanded: boolean;
  onToggle: () => void;
}) {
  const live = useLiveListen(conversation.id);
  const { listening } = live;
  const toggleButton = useRef<HTMLButtonElement | null>(null);
  const listenButtonRef = useRef<HTMLButtonElement | null>(null);
  /** The control in the card that had the focus last. */
  const focused = useRef<Element | null>(null);
  // A change of size or of listening can remove the control that has the focus: Expand moves
  // to the header on a press, and the small card has no Expand once listening ends. The focus
  // then goes to the size button in its new place, or to Listen.
  useLayoutEffect(() => {
    const lost = focused.current;
    if (!lost || lost.isConnected || document.activeElement !== document.body) return;
    (toggleButton.current ?? listenButtonRef.current)?.focus({ preventScroll: true });
  }, [expanded, listening]);
  const onAir = LIVE_STATUSES.includes(conversation.status) || listening;
  const listenButton = onAir && (
    <Button ref={listenButtonRef} variant="outline" size="sm" onClick={live.toggle}>
      {listening ? "Stop listening" : "Listen"}
    </Button>
  );
  // Before Listen there is nothing more to show at full size.
  const toggle = (!onAir || listening || expanded) && (
    <SizeToggle expanded={expanded} buttonRef={toggleButton} onPress={onToggle} />
  );
  let content;
  if (onAir) {
    content = (
      <LiveAudio
        view={live.view}
        listening={listening}
        expanded={expanded}
        listenButton={listenButton}
        toggle={toggle}
      />
    );
  } else {
    // The player keeps its place in the card at both sizes, so the playback goes on.
    content = (
      <RecordingPlayer
        ref={player}
        url={conversation.recording_url}
        name={`yaksh-${conversation.id}`}
        start={start}
        onTime={onTime}
        marks={callMarks(conversation)}
        compact={!expanded}
        trailing={expanded ? undefined : toggle}
      />
    );
  }
  // Both sizes keep the same side padding, so the waveform keeps its width and a zoomed view
  // keeps its place.
  return (
    <Card
      className={cn("shrink-0", !expanded && "overflow-visible py-2.5")}
      onFocus={(event) => {
        focused.current = event.target;
      }}
    >
      {expanded && (
        <CardHeader className="border-b">
          <CardTitle>Audio</CardTitle>
          <CardAction className="flex items-center gap-2">
            {listenButton}
            {toggle}
          </CardAction>
        </CardHeader>
      )}
      <CardContent className={cn("grid grid-cols-1", expanded ? "gap-3" : "gap-1.5")}>
        {content}
      </CardContent>
    </Card>
  );
}

/** Expand or Collapse for the audio card. */
function SizeToggle({
  expanded,
  buttonRef,
  onPress,
}: {
  expanded: boolean;
  buttonRef: RefObject<HTMLButtonElement | null>;
  onPress: () => void;
}) {
  const label = expanded ? "Collapse audio" : "Expand audio";
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            ref={buttonRef}
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            onClick={onPress}
          />
        }
      >
        {expanded ? <ChevronUp /> : <ChevronDown />}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/** A live call's audio: the live waveform once sound arrives, and a line on what plays. In the
 * small card the line also holds Listen and Expand, at the same place before and while
 * listening, so the browser keeps the focus on Listen. */
function LiveAudio({
  view,
  listening,
  expanded,
  listenButton,
  toggle,
}: {
  view: LiveView | null;
  listening: boolean;
  expanded: boolean;
  listenButton: ReactNode;
  toggle: ReactNode;
}) {
  const text = view
    ? `Live, ${clock(view.played * 1000)}`
    : listening
      ? "Waiting for the call's audio."
      : "Listen plays the call while it runs. The recording comes when the call ends.";
  // Small, the line holds the buttons too; expanded, they are in the card's header.
  return (
    <>
      {view && <LiveWaveform view={view} compact={!expanded} />}
      <div className="flex items-center gap-3">
        {!expanded && listenButton}
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-p-400 tabular-nums",
            (expanded || !view) && "text-muted-foreground",
          )}
        >
          {text}
        </span>
        {!expanded && toggle}
      </div>
    </>
  );
}
