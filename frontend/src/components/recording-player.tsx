import {
  Download,
  Link2,
  Pause,
  Play,
  Settings2,
  Volume1,
  Volume2,
  VolumeX,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  type KeyboardEvent,
  memo,
  type PointerEvent,
  type ReactElement,
  type ReactNode,
  type Ref,
  useCallback,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";

import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useObjectUrl } from "@/hooks/use-object-url";
import { copyText } from "@/lib/clipboard";
import type { LiveView } from "@/lib/listen";
import { clock, stamp } from "@/lib/format";
import { type Recording, useRecording } from "@/lib/queries";
import { cn } from "@/lib/utils";

const RATES = [0.75, 1, 1.25, 1.5, 2, 3];
const STEP_S = 5;
const LANES = ["Agent", "Caller"] as const;
/** Bars across one view width of waveform, at every zoom. */
const BARS = 480;
const TICK_STEPS_S = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
/** Heights of the ruler, each lane and the gap between lanes; they match h-5, h-10 and gap-2. */
const RULER_PX = 20;
const LANE_PX = 40;
const GAP_PX = 8;
/** Room under the waveform for a scrollbar, so the controls stay put when one appears. */
const SCROLLBAR_PX = 14;
/** Wheel or pinch travel, in pixels, for one zoom step. */
const WHEEL_STEP = 60;

type Listen = "both" | "agent" | "caller";
type Output = "mono" | "stereo";

const PREFERENCES_KEY = "yaksh.player";

interface Preferences {
  rate: number;
  output: Output;
  volume: number;
}

/** Speed, output and volume carry over between recordings in this browser. */
function loadPreferences(): Preferences {
  const fallback: Preferences = { rate: 1, output: "mono", volume: 1 };
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem(PREFERENCES_KEY) ?? "{}") };
  } catch {
    return fallback;
  }
}

function savePreferences(preferences: Preferences) {
  try {
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences));
  } catch {
    // storage unavailable: the choice lasts for this page only
  }
}

/** The audio graph for one recording: each channel through its own gain, then either into
 * both ears (mono) or its own ear (stereo), then the volume. */
interface Graph {
  context: AudioContext;
  channels: GainNode[];
  merger: ChannelMergerNode;
  volume: GainNode;
}

function connect(graph: Graph, listen: Listen, output: Output, volume: number) {
  graph.channels.forEach((gain, index) => {
    gain.disconnect();
    const heard = listen === "both" || LANES[index].toLowerCase() === listen;
    gain.gain.value = heard ? 1 : 0;
    if (output === "stereo" && graph.channels.length > 1) gain.connect(graph.merger, 0, index);
    else {
      gain.connect(graph.merger, 0, 0);
      gain.connect(graph.merger, 0, 1);
    }
  });
  graph.volume.gain.value = volume;
}

function build(element: HTMLAudioElement, channelCount: number): Graph {
  const context = new AudioContext();
  const source = context.createMediaElementSource(element);
  const splitter = context.createChannelSplitter(channelCount);
  const merger = context.createChannelMerger(2);
  const volume = context.createGain();
  source.connect(splitter);
  const channels = Array.from({ length: channelCount }, (_, index) => {
    const gain = context.createGain();
    splitter.connect(gain, index);
    return gain;
  });
  merger.connect(volume).connect(context.destination);
  return { context, channels, merger, volume };
}

function isMuted(listen: Listen, index: number, count: number): boolean {
  return count > 1 && listen !== "both" && LANES[index].toLowerCase() !== listen;
}

/** The peak of each of BARS equal slices of a lane between two 10 ms buckets. */
function slice(lane: Float32Array, from: number, to: number): number[] {
  const per = (to - from) / BARS;
  return Array.from({ length: BARS }, (_, bar) => {
    const start = Math.floor(from + bar * per);
    const end = Math.max(start + 1, Math.floor(from + (bar + 1) * per));
    let peak = 0;
    for (let i = start; i < Math.min(end, lane.length); i++) peak = Math.max(peak, lane[i]);
    return peak;
  });
}

/** A live call as it plays: the same lanes as the recording, filling from the left, with the
 * played part darker. */
export function LiveWaveform({ view }: { view: LiveView }) {
  const { lanes, span, played } = view;
  const contentPx = RULER_PX + lanes.length * LANE_PX + (lanes.length - 1) * GAP_PX;
  const fraction = played / span;
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-2">
        <div className="grid content-start gap-2 pt-5 text-xs-400 text-muted-foreground">
          {LANES.map((lane) => (
            <span key={lane} className="flex h-10 items-center">
              {lane}
            </span>
          ))}
        </div>
        <div
          role="img"
          aria-label={`Live audio of the call, ${clock(played * 1000)} heard`}
          className="relative"
          style={{ height: contentPx }}
        >
          <Tile
            index={0}
            zoom={1}
            lanes={lanes}
            duration={span}
            listen="both"
            played={fraction * 100}
          />
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 w-px bg-foreground/70"
            style={{ left: `${fraction * 100}%` }}
          />
        </div>
      </div>
      <p className="text-p-400 text-muted-foreground tabular-nums">Live, {clock(played * 1000)}</p>
    </div>
  );
}

/** What a page can ask of a loaded recording. */
export interface PlayerHandle {
  /** Plays from that second of the recording. */
  playFrom: (seconds: number) => void;
}

/** The call recording as one waveform lane per channel: the agent on the left channel, the
 * caller on the right. `start` opens it at that second, for links to a moment. */
/** A stretch of the call to mark on the waveform, in seconds of the recording: a short label
 * for the ruler, a sentence for the hover time, and the classes that colour band and label. */
export interface Mark {
  from: number;
  to: number;
  label: string;
  title: string;
  fill: string;
  text: string;
}

/** How near a band, in pixels, the pointer counts as on it: a short wait is a narrow band. */
const MARK_REACH_PX = 4;

/** Centres a label on a point at `fraction` of the timeline, moved inward where it would pass
 * an end: past the right end it would widen the scroll area that times are measured on. */
function inside(fraction: number): string {
  return `clamp(${-fraction * 100}cqw, -50%, calc(${(1 - fraction) * 100}cqw - 100%))`;
}

export function RecordingPlayer({
  url,
  name,
  start = 0,
  ref,
  onTime,
  marks = [],
}: {
  url: string | null;
  name: string;
  start?: number;
  ref?: Ref<PlayerHandle>;
  /** Hears where playback is, a few times a second and on each seek. */
  onTime?: (seconds: number) => void;
  marks?: Mark[];
}) {
  const recording = useRecording(url);
  if (url === null) {
    return <p className="text-p-400 text-muted-foreground">Available once the call has ended.</p>;
  }
  if (recording.isError) {
    return <p className="text-p-400 text-destructive">The recording did not load.</p>;
  }
  if (recording.isPending) return <Skeleton className="h-40 w-full" />;
  return (
    <Player
      key={url}
      recording={recording.data}
      name={name}
      start={start}
      ref={ref}
      onTime={onTime}
      marks={marks}
    />
  );
}

function Player({
  recording,
  name,
  start,
  ref,
  onTime,
  marks,
}: {
  recording: Recording;
  name: string;
  start: number;
  ref?: Ref<PlayerHandle>;
  onTime?: (seconds: number) => void;
  marks: Mark[];
}) {
  const { duration, lanes } = recording;
  const src = useObjectUrl(recording.blob);
  const stereo = lanes.length > 1;
  const maxZoom = 2 ** Math.max(0, Math.floor(Math.log2(lanes[0].length / BARS)));
  const contentPx = RULER_PX + lanes.length * LANE_PX + (lanes.length - 1) * GAP_PX;

  const audio = useRef<HTMLAudioElement | null>(null);
  const graph = useRef<Graph | null>(null);
  const viewport = useRef<HTMLDivElement | null>(null);
  const frame = useRef(0);
  const scrub = useRef<{ resume: boolean } | null>(null);
  const zoomLevel = useRef(1);
  const wheelTravel = useRef(0);
  const [initial] = useState(loadPreferences);
  const unmuted = useRef(initial.volume || 1);
  const [time, setTime] = useState(start);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(initial.rate);
  const [listen, setListen] = useState<Listen>("both");
  const [output, setOutput] = useState<Output>(initial.output);
  const [volume, setVolume] = useState(initial.volume);
  const [hover, setHover] = useState<{ fraction: number; mark?: Mark } | null>(null);
  const [shift, setShift] = useState(0);
  const hint = useRef<HTMLSpanElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [first, setFirst] = useState(0);

  /** Zooms to `level`, keeping `anchor` (a moment and its distance from the left of the view)
   * in place: by default the playhead when it is in view, else the middle of the view. */
  const zoomTo = useCallback(
    (level: number, anchor?: { time: number; x: number }) => {
      const view = viewport.current;
      const next = Math.min(Math.max(level, 1), maxZoom);
      if (!view || next === zoomLevel.current) return;
      const width = view.clientWidth;
      const playhead = audio.current?.currentTime ?? 0;
      const playheadX = (playhead / duration) * view.scrollWidth - view.scrollLeft;
      const point =
        anchor ??
        (playheadX >= 0 && playheadX <= width
          ? { time: playhead, x: playheadX }
          : { time: ((view.scrollLeft + width / 2) / view.scrollWidth) * duration, x: width / 2 });
      const left = Math.min(
        Math.max((point.time / duration) * width * next - point.x, 0),
        width * (next - 1),
      );
      zoomLevel.current = next;
      flushSync(() => {
        setHover(null);
        setZoom(next);
        setFirst(Math.floor(left / width));
      });
      view.scrollLeft = left;
    },
    [duration, maxZoom],
  );

  // A pinch, or a scroll with Ctrl or Cmd held, zooms around the pointer. The listener is not
  // passive so that the browser does not zoom the whole page instead.
  const attachViewport = useCallback(
    (view: HTMLDivElement | null) => {
      viewport.current = view;
      if (!view) return;
      const wheel = (event: WheelEvent) => {
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        if (Math.sign(event.deltaY) !== Math.sign(wheelTravel.current)) wheelTravel.current = 0;
        wheelTravel.current += event.deltaY;
        if (Math.abs(wheelTravel.current) < WHEEL_STEP) return;
        const x = event.clientX - view.getBoundingClientRect().left;
        const time = ((view.scrollLeft + x) / view.scrollWidth) * duration;
        zoomTo(zoomLevel.current * (wheelTravel.current < 0 ? 2 : 0.5), { time, x });
        wheelTravel.current = 0;
      };
      view.addEventListener("wheel", wheel, { passive: false });
      return () => view.removeEventListener("wheel", wheel);
    },
    [duration, zoomTo],
  );

  const attachAudio = useCallback((element: HTMLAudioElement | null) => {
    audio.current = element;
    return () => {
      void graph.current?.context.close();
      graph.current = null;
    };
  }, []);

  /** Scrolls a zoomed view to show `seconds`. With `onlyAtEdge`, only when playback has just
   * crossed the right edge, so a view scrolled away on purpose is left alone. */
  const reveal = (seconds: number, onlyAtEdge: boolean) => {
    const view = viewport.current;
    if (!view || view.scrollWidth <= view.clientWidth) return;
    const x = (seconds / duration) * view.scrollWidth;
    const right = view.scrollLeft + view.clientWidth;
    if (x >= view.scrollLeft && x <= right) return;
    if (onlyAtEdge && (x < right || x - right > view.clientWidth * 0.05)) return;
    view.scrollLeft = x - view.clientWidth * 0.1;
  };
  const follow = () => {
    const element = audio.current;
    if (!element) return;
    setTime(element.currentTime);
    reveal(element.currentTime, true);
    if (!element.paused) frame.current = requestAnimationFrame(follow);
  };
  const seek = (seconds: number, show = false) => {
    const element = audio.current;
    if (!element) return;
    element.currentTime = Math.min(Math.max(seconds, 0), duration);
    setTime(element.currentTime);
    if (show) reveal(element.currentTime, false);
  };
  /** Plays through the audio graph, which routes the channels and sets the volume. Browsers
   * allow a graph only after a user gesture, so it is built on the first play. */
  const play = async () => {
    const element = audio.current;
    if (!element) return;
    if (!graph.current) {
      graph.current = build(element, lanes.length);
      connect(graph.current, listen, output, volume);
    }
    await graph.current.context.resume();
    await element.play();
  };
  useImperativeHandle(ref, () => ({
    playFrom(seconds: number) {
      seek(seconds, true);
      void play();
    },
  }));
  const at = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return Math.min(Math.max((event.clientX - box.left) / box.width, 0), 1);
  };
  // Scrubbing jumps on press and follows the pointer 1:1, even outside the waveform. A playing
  // call pauses while it is dragged and carries on from where it is released.
  const press = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !audio.current) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    scrub.current = { resume: !audio.current.paused };
    audio.current.pause();
    seek(at(event) * duration);
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const fraction = at(event);
    const width = event.currentTarget.getBoundingClientRect().width;
    const distance = (mark: Mark) =>
      Math.max(mark.from / duration - fraction, fraction - mark.to / duration, 0) * width;
    const nearest = marks.reduce<Mark | undefined>(
      (best, mark) => (best && distance(best) <= distance(mark) ? best : mark),
      undefined,
    );
    setHover({
      fraction,
      mark: nearest && distance(nearest) <= MARK_REACH_PX ? nearest : undefined,
    });
    if (!scrub.current) return;
    seek(fraction * duration);
    // Dragging past either edge of a zoomed view scrolls it along.
    const view = viewport.current;
    const box = view?.getBoundingClientRect();
    if (view && box && event.clientX > box.right) view.scrollLeft += event.clientX - box.right;
    else if (view && box && event.clientX < box.left) view.scrollLeft -= box.left - event.clientX;
  };
  const release = () => {
    if (scrub.current?.resume) void play();
    scrub.current = null;
  };
  const toggle = () => {
    if (audio.current?.paused) void play();
    else audio.current?.pause();
  };
  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const actions: Record<string, () => void> = {
      ArrowRight: () => seek(time + STEP_S, true),
      ArrowLeft: () => seek(time - STEP_S, true),
      Home: () => seek(0, true),
      End: () => seek(duration, true),
      " ": toggle,
      "+": () => zoomTo(zoom * 2),
      "=": () => zoomTo(zoom * 2),
      "-": () => zoomTo(zoom / 2),
      "0": () => zoomTo(1),
      m: toggleMute,
      M: toggleMute,
    };
    const action = actions[event.key];
    if (!action) return;
    event.preventDefault();
    action();
  };
  const route = (next: { listen?: Listen; output?: Output; volume?: number }) => {
    const settings = { listen, output, volume, ...next };
    if (next.listen) setListen(next.listen);
    if (next.output) setOutput(next.output);
    if (next.volume !== undefined) setVolume(next.volume);
    if (graph.current) connect(graph.current, settings.listen, settings.output, settings.volume);
    savePreferences({ rate, output: settings.output, volume: settings.volume });
  };
  const toggleMute = () => {
    if (volume > 0) unmuted.current = volume;
    route({ volume: volume > 0 ? 0 : unmuted.current });
  };
  const changeRate = (next: number) => {
    if (audio.current) audio.current.playbackRate = next;
    setRate(next);
    savePreferences({ rate: next, output, volume });
  };
  const copyMoment = () => {
    const link = new URL(window.location.href);
    link.searchParams.set("t", String(Math.floor(time)));
    void copyText(link.toString(), `Link to ${clock(Math.floor(time) * 1000)} copied`);
  };

  // The hover time sits centred on the pointer, and moves inward where an edge of the view
  // would cut it off.
  useLayoutEffect(() => {
    const view = viewport.current;
    const label = hint.current;
    if (!hover || !view || !label) return;
    const x = hover.fraction * view.scrollWidth - view.scrollLeft;
    const width = label.offsetWidth;
    setShift(Math.max(-x, Math.min(-width / 2, view.clientWidth - x - width)));
  }, [hover]);

  const fraction = duration > 0 ? time / duration : 0;
  const tiles: number[] = [];
  for (let index = Math.max(0, first - 1); index <= Math.min(zoom - 1, first + 2); index++) {
    tiles.push(index);
  }

  return (
    <div className="grid gap-3 transition-opacity duration-200 ease-out starting:opacity-0">
      <audio
        ref={attachAudio}
        src={src}
        preload="auto"
        onLoadedMetadata={(event) => {
          event.currentTarget.currentTime = Math.min(start, duration);
          event.currentTarget.playbackRate = rate;
        }}
        onPlay={() => {
          setPlaying(true);
          frame.current = requestAnimationFrame(follow);
        }}
        onPause={() => {
          cancelAnimationFrame(frame.current);
          setPlaying(false);
          follow();
        }}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(event) => onTime?.(event.currentTarget.currentTime)}
      />
      <div className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-2">
        <div className="grid content-start gap-2 pt-5 text-xs-400 text-muted-foreground">
          {lanes.map((_, index) => (
            <span key={index} className="flex h-10 items-center">
              {stereo ? LANES[index] : "Call"}
            </span>
          ))}
        </div>
        <div
          ref={attachViewport}
          tabIndex={-1}
          onScroll={(event) =>
            setFirst(Math.floor(event.currentTarget.scrollLeft / event.currentTarget.clientWidth))
          }
          className="overflow-x-auto overflow-y-hidden [scrollbar-width:thin]"
          style={{ height: contentPx + SCROLLBAR_PX }}
        >
          <div
            role="slider"
            tabIndex={0}
            aria-label="Position in the recording"
            aria-valuemin={0}
            aria-valuemax={Math.round(duration)}
            aria-valuenow={Math.round(time)}
            aria-valuetext={`${clock(time * 1000)} of ${clock(duration * 1000)}`}
            onPointerDown={press}
            onPointerMove={move}
            onPointerUp={release}
            onPointerCancel={release}
            onPointerLeave={() => setHover(null)}
            onKeyDown={key}
            className="@container relative cursor-pointer touch-none rounded-sm outline-none select-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
            style={{ width: `${zoom * 100}%`, height: contentPx }}
          >
            {tiles.map((index) => (
              <Tile
                key={`${zoom}-${index}`}
                index={index}
                zoom={zoom}
                lanes={lanes}
                duration={duration}
                listen={listen}
                played={Math.min(Math.max(fraction * zoom - index, 0), 1) * 100}
              />
            ))}
            {marks.map((mark) => (
              <span
                key={`${mark.from}-${mark.to}`}
                aria-hidden
                className="pointer-events-none absolute inset-y-0"
                style={{
                  left: `${(mark.from / duration) * 100}%`,
                  width: `${(Math.max(mark.to - mark.from, 0) / duration) * 100}%`,
                }}
              >
                <span
                  className={cn("absolute inset-x-0 bottom-0", mark.fill)}
                  style={{ top: RULER_PX }}
                />
                <span
                  className={cn(
                    "absolute top-0.5 left-1/2 rounded-sm bg-card px-0.5 text-xxs-600 whitespace-nowrap tabular-nums",
                    mark.text,
                  )}
                  style={{ translate: inside((mark.from + mark.to) / 2 / duration) }}
                >
                  {mark.label}
                </span>
              </span>
            ))}
            {hover && (
              <span
                aria-hidden
                className="pointer-events-none absolute inset-y-0"
                style={{ left: `${hover.fraction * 100}%` }}
              >
                <span className="absolute inset-y-0 left-0 w-px bg-foreground/25" />
                <span
                  ref={hint}
                  className="absolute top-0 left-0 z-10 rounded-sm bg-popover px-1.5 py-0.5 text-xxs-600 whitespace-nowrap tabular-nums shadow-1 ring-1 ring-border"
                  style={{ translate: `${shift}px` }}
                >
                  {clock(hover.fraction * duration * 1000)}
                  {hover.mark && ` · ${hover.mark.title}`}
                </span>
              </span>
            )}
            <span
              aria-hidden
              className="pointer-events-none absolute inset-y-0 w-px bg-foreground/70"
              style={{ left: `${fraction * 100}%` }}
            />
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1">
        <Button size="icon-sm" aria-label={playing ? "Pause" : "Play"} onClick={toggle}>
          {playing ? <Pause /> : <Play />}
        </Button>
        <span className="ml-2 text-p-400 tabular-nums">
          {clock(time * 1000)}
          <span className="text-muted-foreground"> / {clock(duration * 1000)}</span>
        </span>
        <div className="ml-auto flex items-center gap-1">
          {maxZoom > 1 && (
            <>
              <Hint
                label="Zoom out"
                shortcut="−"
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Zoom out"
                    disabled={zoom === 1}
                    onClick={() => zoomTo(zoom / 2)}
                  />
                }
              >
                <ZoomOut />
              </Hint>
              <Hint
                label="Zoom in"
                shortcut="+"
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Zoom in"
                    disabled={zoom === maxZoom}
                    onClick={() => zoomTo(zoom * 2)}
                  />
                }
              >
                <ZoomIn />
              </Hint>
              <Hint
                label="Show the whole call"
                shortcut="0"
                render={
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={zoom === 1}
                    onClick={() => zoomTo(1)}
                  />
                }
              >
                Fit
              </Hint>
              <Divider />
            </>
          )}
          <Popover>
            <Hint
              label="Volume"
              shortcut="M"
              render={
                <PopoverTrigger
                  render={<Button variant="ghost" size="icon-sm" aria-label="Volume" />}
                />
              }
            >
              <VolumeIcon volume={volume} />
            </Hint>
            <PopoverContent align="end" className="w-64">
              <div className="grid gap-1.5">
                <span className="text-xs-400 text-muted-foreground">Volume</span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={volume === 0 ? "Unmute" : "Mute"}
                    onClick={toggleMute}
                  >
                    <VolumeIcon volume={volume} />
                  </Button>
                  <div className="min-w-0 flex-1">
                    <Slider
                      aria-label="Volume"
                      min={0}
                      max={1}
                      step={0.05}
                      value={volume}
                      onValueChange={(next) => route({ volume: next as number })}
                    />
                  </div>
                  <span className="w-10 text-right text-p-400 tabular-nums">
                    {Math.round(volume * 100)}%
                  </span>
                </div>
              </div>
            </PopoverContent>
          </Popover>
          <Hint
            label="Copy link to this moment"
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Copy link to this moment"
                onClick={copyMoment}
              />
            }
          >
            <Link2 />
          </Hint>
          <Hint
            label="Download recording"
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Download recording"
                nativeButton={false}
                render={<a href={src} download={`${name}.wav`} />}
              />
            }
          >
            <Download />
          </Hint>
          <Popover>
            <PopoverTrigger
              render={<Button variant="ghost" size="sm" aria-label="Playback settings" />}
            >
              <Settings2 />
              <span className="tabular-nums">{rate}×</span>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto">
              {stereo && (
                <div className="flex gap-6">
                  <Segmented
                    label="Listen to"
                    value={listen}
                    options={[
                      { value: "both", label: "Both" },
                      { value: "agent", label: "Agent" },
                      { value: "caller", label: "Caller" },
                    ]}
                    onChange={(value) => route({ listen: value })}
                  />
                  <Segmented
                    label="Output"
                    value={output}
                    options={[
                      { value: "mono", label: "Mono" },
                      { value: "stereo", label: "Stereo" },
                    ]}
                    onChange={(value) => route({ output: value })}
                  />
                </div>
              )}
              <Segmented
                label="Speed"
                value={rate}
                options={RATES.map((value) => ({ value, label: `${value}×` }))}
                onChange={changeRate}
              />
            </PopoverContent>
          </Popover>
        </div>
      </div>
    </div>
  );
}

/** One view-width slice of the timeline: its ruler and every lane. Only the slices around the
 * view are mounted, so a long call at a deep zoom stays light. */
const Tile = memo(function Tile({
  index,
  zoom,
  lanes,
  duration,
  listen,
  played,
}: {
  index: number;
  zoom: number;
  lanes: Float32Array[];
  duration: number;
  listen: Listen;
  played: number;
}) {
  const peaks = useMemo(
    () =>
      lanes.map((lane) =>
        slice(lane, (index * lane.length) / zoom, ((index + 1) * lane.length) / zoom),
      ),
    [lanes, index, zoom],
  );
  const span = duration / zoom;
  const step =
    TICK_STEPS_S.find((candidate) => candidate >= span / 8) ??
    TICK_STEPS_S[TICK_STEPS_S.length - 1];
  // A tick too close to the end of the call has no room for its label.
  const last = Math.min((index + 1) * span, duration - span * 0.04);
  const ticks: number[] = [];
  for (let tick = Math.ceil((index * span) / step) * step; tick < last; tick += step) {
    ticks.push(tick);
  }
  return (
    <div
      className="absolute inset-y-0"
      style={{ left: `${(index / zoom) * 100}%`, width: `${100 / zoom}%` }}
    >
      <div className="relative h-5">
        {ticks.map((tick) => (
          <span
            key={tick}
            className="absolute top-0 h-full border-l pl-1 text-xxs-400 leading-4 text-muted-foreground tabular-nums"
            style={{ left: `${((tick - index * span) / span) * 100}%` }}
          >
            {stamp(tick)}
          </span>
        ))}
      </div>
      <div className="relative">
        <Lanes peaks={peaks} listen={listen} className="opacity-30" />
        <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - played}% 0 0)` }}>
          <Lanes peaks={peaks} listen={listen} />
        </div>
      </div>
    </div>
  );
});

const Lanes = memo(function Lanes({
  peaks,
  listen,
  className = "",
}: {
  peaks: number[][];
  listen: Listen;
  className?: string;
}) {
  return (
    <div className={`grid gap-2 ${className}`}>
      {peaks.map((lane, index) => (
        <svg
          key={index}
          viewBox={`0 0 ${lane.length} 2`}
          preserveAspectRatio="none"
          aria-hidden
          className={`h-10 w-full fill-current transition-opacity duration-150 ${index === 0 ? "text-foreground" : "text-chart-1"} ${isMuted(listen, index, peaks.length) ? "opacity-30" : ""}`}
        >
          {lane.map((peak, bar) => {
            const height = Math.max(peak, 0.02);
            return <rect key={bar} x={bar + 0.15} width={0.7} y={1 - height} height={height * 2} />;
          })}
        </svg>
      ))}
    </div>
  );
});

function Hint({
  label,
  shortcut,
  render,
  children,
}: {
  label: string;
  shortcut?: string;
  render: ReactElement;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger render={render}>{children}</TooltipTrigger>
      <TooltipContent>
        {label}
        {shortcut && <kbd className="ml-2 font-sans opacity-60">{shortcut}</kbd>}
      </TooltipContent>
    </Tooltip>
  );
}

function VolumeIcon({ volume }: { volume: number }) {
  if (volume === 0) return <VolumeX />;
  return volume < 0.5 ? <Volume1 /> : <Volume2 />;
}

function Divider() {
  return <span aria-hidden className="mx-1 h-5 w-px bg-border" />;
}
