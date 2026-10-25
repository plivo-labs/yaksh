/** The lanes of a call's waveform, one for each channel, and their sizes. */

export const LANES = ["Agent", "Caller"] as const;
/** Bars across one view width of waveform, at every zoom. */
export const BARS = 480;
/** Heights of the ruler, each lane and the gap between lanes; they match h-5, h-10 and gap-2. */
export const RULER_PX = 20;
const LANE_PX = 40;
const GAP_PX = 8;

export type Listen = "both" | "agent" | "caller";

/** The height of the ruler and that many lanes under it. */
export function waveformHeight(lanes: number): number {
  return RULER_PX + lanes * LANE_PX + (lanes - 1) * GAP_PX;
}

/** The peak of each of BARS equal slices of a lane between two 10 ms buckets. */
export function slice(lane: Float32Array, from: number, to: number): number[] {
  const per = (to - from) / BARS;
  return Array.from({ length: BARS }, (_, bar) => {
    const start = Math.floor(from + bar * per);
    const end = Math.max(start + 1, Math.floor(from + (bar + 1) * per));
    let peak = 0;
    for (let i = start; i < Math.min(end, lane.length); i++) peak = Math.max(peak, lane[i]);
    return peak;
  });
}
