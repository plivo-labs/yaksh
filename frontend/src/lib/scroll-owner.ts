/** Who moved the transcript, from the events of its scroll area: the call's player shrinks only
 * when the user scrolls down, and grows when the user scrolls up to, or at, the very top. */

/** How far down a scroll by the user goes before the player shrinks. */
export const SHRINK_AFTER_PX = 40;

/** How long a wheel, touch or key event owns the scroll: momentum keeps sending wheel events,
 * so a fling stays the user's. */
const GESTURE_MS = 300;

/** A gap in wheel events longer than this starts a new gesture. */
const PAUSE_MS = 120;

export interface ScrollOwner {
  /** Until when the user's last gesture owns the scroll, in ms on the event clock. */
  until: number;
  /** A press on the scroll area, such as a drag of its scrollbar, owns the scroll until release. */
  pressed: boolean;
  /** Where the last scroll left the transcript. */
  top: number;
  /** When the last gesture event came. */
  last: number;
  /** The user pressed Expand: the rest of that gesture, such as its momentum, owns nothing. */
  held: boolean;
}

export type ScrollEvent =
  /** A wheel turn, a touch move or a scroll key on the scroll area. */
  | { kind: "gesture"; at: number; up: boolean; top: number }
  | { kind: "press"; down: boolean }
  /** What scrolls next is not the user's gesture: Follow audio, a judge's quote, a press on a
   * turn or focus that moves to one, which can scroll it into view, or a new window size. */
  | { kind: "code" }
  | { kind: "expanded" }
  /** The player changed size, and the browser left the transcript at `top`: a transcript past
   * its new end moves back to it, which is not a scroll by the user. */
  | { kind: "resized"; top: number }
  | { kind: "scroll"; at: number; top: number };

export type Resize = "shrink" | "expand" | null;

export const START: ScrollOwner = { until: 0, pressed: false, top: 0, last: 0, held: false };

export function scrolled(owner: ScrollOwner, event: ScrollEvent): [ScrollOwner, Resize] {
  switch (event.kind) {
    case "gesture": {
      const held = owner.held && event.at - owner.last <= PAUSE_MS;
      return [
        { ...owner, held, last: event.at, until: held ? 0 : event.at + GESTURE_MS },
        !held && event.up && event.top <= 0 ? "expand" : null,
      ];
    }
    case "press":
      return [{ ...owner, pressed: event.down, held: false }, null];
    case "code":
      return [{ ...owner, until: 0, pressed: false }, null];
    case "expanded":
      return [{ ...owner, until: 0, pressed: false, held: true }, null];
    case "resized":
      return [{ ...owner, top: event.top }, null];
    case "scroll": {
      const next = { ...owner, top: event.top };
      // A scroll that does not move, such as the browser's report of a clamp after "resized",
      // keeps no ownership alive.
      if (event.top === owner.top) return [next, null];
      if (!owner.pressed && event.at >= owner.until) return [next, null];
      // An owned scroll keeps owning the motion it is part of, such as a touch fling that goes on
      // after the finger lifts.
      const owned = { ...next, until: Math.max(owner.until, event.at + GESTURE_MS) };
      if (event.top > owner.top && event.top > SHRINK_AFTER_PX) return [owned, "shrink"];
      if (event.top < owner.top && event.top <= 0) return [owned, "expand"];
      return [owned, null];
    }
  }
}
