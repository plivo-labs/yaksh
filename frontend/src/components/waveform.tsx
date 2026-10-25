import { memo, useMemo } from "react";

import { clock, stamp } from "@/lib/format";
import type { LiveView } from "@/lib/listen";
import { cn } from "@/lib/utils";
import { LANES, type Listen, slice, waveformHeight } from "@/lib/waveform";

const TICK_STEPS_S = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];

function isMuted(listen: Listen, index: number, count: number): boolean {
  return count > 1 && listen !== "both" && LANES[index].toLowerCase() !== listen;
}

/** A live call as it plays: the same lanes as the recording, filling from the left, with the
 * played part darker. */
export function LiveWaveform({ view }: { view: LiveView }) {
  const { lanes, span, played } = view;
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
          style={{ height: waveformHeight(lanes.length) }}
        >
          <Tile
            index={0}
            zoom={1}
            lanes={lanes}
            duration={span}
            listen="both"
            played={fraction * 100}
          />
          <Playhead fraction={fraction} />
        </div>
      </div>
      <p className="text-p-400 text-muted-foreground tabular-nums">Live, {clock(played * 1000)}</p>
    </div>
  );
}

/** Where playback is, at `fraction` of the width. */
export function Playhead({ fraction }: { fraction: number }) {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute inset-y-0 w-px bg-foreground/70"
      style={{ left: `${fraction * 100}%` }}
    />
  );
}

/** One view-width slice of the timeline: its ruler and every lane. Only the slices around the
 * view are mounted, so a long call at a deep zoom stays light. */
export const Tile = memo(function Tile({
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

/** A lane's bars as one path: one element per lane, not one per bar, so a style change on
 * the player recalculates a few elements, not thousands. */
function bars(lane: number[]): string {
  return lane
    .map((peak, bar) => {
      const height = Math.max(peak, 0.02);
      return `M${bar + 0.15} ${1 - height}h0.7v${height * 2}h-0.7z`;
    })
    .join("");
}

export const Lanes = memo(function Lanes({
  peaks,
  listen,
  className,
  lane: laneHeight = "h-10",
}: {
  peaks: number[][];
  listen: Listen;
  className?: string;
  /** The height class of each lane. */
  lane?: string;
}) {
  return (
    <div className={cn("grid gap-2", className)}>
      {peaks.map((lane, index) => (
        <svg
          key={index}
          viewBox={`0 0 ${lane.length} 2`}
          preserveAspectRatio="none"
          aria-hidden
          className={cn(
            "w-full fill-current transition-opacity duration-150",
            laneHeight,
            index === 0 ? "text-foreground" : "text-chart-1",
            isMuted(listen, index, peaks.length) && "opacity-30",
          )}
        >
          <path d={bars(lane)} />
        </svg>
      ))}
    </div>
  );
});
