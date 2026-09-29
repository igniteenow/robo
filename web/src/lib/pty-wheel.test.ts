import { describe, expect, it } from "vitest";

import {
  WheelLines,
  cellAtPoint,
  sgrWheelReport,
  sgrWheelReports,
  wheelDeltaToLines,
} from "./pty-wheel";

describe("sgrWheelReport", () => {
  it("encodes wheel up/down as the SGR reports the TUI parses", () => {
    expect(sgrWheelReport("up", 10, 5)).toBe("\x1b[<64;10;5M");
    expect(sgrWheelReport("down", 1, 1)).toBe("\x1b[<65;1;1M");
  });

  it("never emits a zero or negative coordinate", () => {
    expect(sgrWheelReport("up", 0, -3)).toBe("\x1b[<64;1;1M");
  });
});

describe("wheelDeltaToLines", () => {
  it("converts pixel, line and page deltas to terminal lines", () => {
    expect(wheelDeltaToLines(100, 0, 20, 40)).toBe(5);
    expect(wheelDeltaToLines(3, 1, 20, 40)).toBe(3);
    expect(wheelDeltaToLines(1, 2, 20, 40)).toBe(40);
    expect(wheelDeltaToLines(100, 0, 0, 40)).toBe(0);
  });
});

describe("WheelLines", () => {
  it("reports every whole line a notch moves, like scrolling a web page", () => {
    const acc = new WheelLines();
    // A mouse notch is ~100px = 5 lines.
    expect(acc.add(5)).toBe(5);
    expect(acc.add(-5)).toBe(-5);
    expect(acc.add(2.5)).toBe(2);
    expect(acc.add(0.5)).toBe(1);
  });

  it("waits for a whole line on small trackpad deltas", () => {
    const acc = new WheelLines();
    expect(acc.add(0.4)).toBe(0);
    expect(acc.add(0.4)).toBe(0);
    expect(acc.add(0.4)).toBe(1);
  });

  it("drops leftovers when the direction flips", () => {
    const acc = new WheelLines();
    acc.add(0.9);
    expect(acc.add(-1)).toBe(-1);
  });
});

describe("sgrWheelReports", () => {
  it("sends one report per line, together, in the wheel's direction", () => {
    expect(sgrWheelReports(3, 4, 2, 40)).toBe("\x1b[<65;4;2M".repeat(3));
    expect(sgrWheelReports(-2, 4, 2, 40)).toBe("\x1b[<64;4;2M".repeat(2));
  });

  it("sends nothing under a line and at most a screenful", () => {
    expect(sgrWheelReports(0, 1, 1, 40)).toBe("");
    expect(sgrWheelReports(500, 1, 1, 40)).toBe("\x1b[<65;1;1M".repeat(40));
    expect(sgrWheelReports(-3, 1, 1, 0)).toBe("\x1b[<64;1;1M");
  });
});

describe("cellAtPoint", () => {
  const rect = { left: 100, top: 50, width: 800, height: 400 };

  it("maps a point to its 1-based cell", () => {
    // 80x20 grid → 10px x 20px cells.
    expect(cellAtPoint(100, 50, rect, 80, 20)).toEqual({ col: 1, row: 1 });
    expect(cellAtPoint(155, 95, rect, 80, 20)).toEqual({ col: 6, row: 3 });
  });

  it("clamps points outside the grid", () => {
    expect(cellAtPoint(0, 0, rect, 80, 20)).toEqual({ col: 1, row: 1 });
    expect(cellAtPoint(5000, 5000, rect, 80, 20)).toEqual({ col: 80, row: 20 });
  });
});
