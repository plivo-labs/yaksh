import { describe, expect, test } from "bun:test";

import { type Resize, START, type ScrollEvent, type ScrollOwner, scrolled } from "./scroll-owner";

function run(events: ScrollEvent[], from: ScrollOwner = START): Resize[] {
  let owner = from;
  return events.map((event) => {
    const [next, resize] = scrolled(owner, event);
    owner = next;
    return resize;
  });
}

function scroll(at: number, top: number): ScrollEvent {
  return { kind: "scroll", at, top };
}

describe("the player's size follows only the user's scrolling", () => {
  test("a wheel scroll down past 40 px shrinks it", () => {
    expect(
      run([{ kind: "gesture", at: 0, up: false, top: 0 }, scroll(10, 30), scroll(20, 90)]),
    ).toEqual([null, null, "shrink"]);
  });

  test("a scroll by the page right after a wheel turn does not", () => {
    expect(
      run([{ kind: "gesture", at: 0, up: false, top: 0 }, { kind: "code" }, scroll(10, 300)]),
    ).toEqual([null, null, null]);
  });

  test("a scroll up never shrinks it, however far down it is", () => {
    expect(
      run([scroll(0, 600), { kind: "gesture", at: 100, up: true, top: 600 }, scroll(110, 500)]),
    ).toEqual([null, null, null]);
  });

  test("a held scrollbar drag shrinks it after any length of hold", () => {
    expect(run([{ kind: "press", down: true }, scroll(5000, 120)])).toEqual([null, "shrink"]);
  });

  test("after Expand, the rest of the same fling does not shrink it, and a new gesture does", () => {
    expect(
      run([
        { kind: "gesture", at: 0, up: false, top: 0 },
        scroll(10, 90),
        { kind: "expanded" },
        { kind: "gesture", at: 30, up: false, top: 90 },
        scroll(40, 150),
        { kind: "gesture", at: 400, up: false, top: 150 },
        scroll(410, 220),
      ]),
    ).toEqual([null, "shrink", null, null, null, null, "shrink"]);
  });

  test("a drag or a key that scrolls up to the top grows it, and a scroll by the page does not", () => {
    const far = { ...START, top: 300 };
    expect(run([{ kind: "press", down: true }, scroll(0, 120), scroll(10, 0)], far)).toEqual([
      null,
      null,
      "expand",
    ]);
    expect(run([{ kind: "gesture", at: 0, up: true, top: 300 }, scroll(10, 0)], far)).toEqual([
      null,
      "expand",
    ]);
    expect(
      run([{ kind: "gesture", at: 0, up: true, top: 300 }, { kind: "code" }, scroll(10, 0)], far),
    ).toEqual([null, null, null]);
  });

  test("the browser's move back to the top after a shrink does not grow it", () => {
    expect(
      run([
        { kind: "gesture", at: 0, up: false, top: 0 },
        scroll(10, 60),
        { kind: "resized", top: 0 },
        { kind: "gesture", at: 20, up: false, top: 0 },
        scroll(30, 0),
      ]),
    ).toEqual([null, "shrink", null, null, null]);
  });

  test("the browser's report of that move does not keep the user's ownership alive", () => {
    expect(
      run([
        { kind: "gesture", at: 0, up: false, top: 0 },
        scroll(10, 60),
        { kind: "resized", top: 30 },
        scroll(200, 30),
        scroll(400, 0),
      ]),
    ).toEqual([null, "shrink", null, null, null]);
  });

  test("a touch fling that goes on after the finger lifts still grows it at the top", () => {
    expect(
      run(
        [
          { kind: "gesture", at: 0, up: true, top: 900 },
          scroll(100, 600),
          scroll(250, 300),
          scroll(400, 0),
        ],
        { ...START, top: 900 },
      ),
    ).toEqual([null, null, null, "expand"]);
  });

  test("a scroll up grows it only at the very top", () => {
    expect(
      run([
        { kind: "gesture", at: 0, up: true, top: 30 },
        { kind: "gesture", at: 10, up: true, top: 0 },
      ]),
    ).toEqual([null, "expand"]);
  });
});
