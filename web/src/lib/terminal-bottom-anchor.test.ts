import { describe, expect, it } from "vitest";

import { bottomAnchorOffsetRows } from "./terminal-bottom-anchor";

const buffer = (
  rows: number,
  usedRows: number,
  cursorY: number,
  baseY = 0,
) => ({
  rows,
  baseY,
  cursorY,
  lineIsBlank: (y: number) => y >= usedRows,
});

describe("bottomAnchorOffsetRows", () => {
  it("pushes a short chat down so the input box sits at the bottom", () => {
    // 40-row pane, TUI drew 12 rows, cursor parked on its last row.
    expect(bottomAnchorOffsetRows(buffer(40, 12, 11))).toBe(28);
  });

  it("does not shift a pane the conversation already fills", () => {
    expect(bottomAnchorOffsetRows(buffer(40, 40, 39))).toBe(0);
  });

  it("does not shift once there is scrollback", () => {
    expect(bottomAnchorOffsetRows(buffer(40, 12, 11, 5))).toBe(0);
  });

  it("keeps the cursor row on screen even when it is below the text", () => {
    expect(bottomAnchorOffsetRows(buffer(40, 12, 20))).toBe(19);
  });

  it("is a no-op for an unsized terminal", () => {
    expect(bottomAnchorOffsetRows(buffer(0, 0, 0))).toBe(0);
  });
});
