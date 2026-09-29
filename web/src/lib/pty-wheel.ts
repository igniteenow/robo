/**
 * Scrolling the full-screen TUI from the browser.
 *
 * The dashboard runs the TUI full screen (alternate buffer), so xterm has no
 * scrollback of its own: the transcript scrolls inside the TUI. TUI mouse
 * capture stays off so people can still select and copy text, so xterm won't
 * report the wheel by itself. ChatPage turns wheel and touch-swipe movement
 * into SGR wheel reports, which the TUI parses as scroll input whether or not
 * it enabled mouse tracking.
 *
 * The wheel moves the transcript as far as it moves a web page: one report
 * per whole line of wheel movement (a typical mouse notch is ~5 lines), all
 * sent in ONE message. The TUI reads a same-instant batch as one row per
 * report on top of its own boost for the first (the xterm.js wheel curve the
 * dashboard selects in web_server._apply_browser_terminal_identity), so a
 * notch moves ~6 rows and sustained scrolling speeds up from there. One
 * report per event — VS Code's cadence — moved only 2-3 rows per notch.
 */

/** SGR wheel report at a 1-based cell (64 = wheel up, 65 = wheel down). */
export function sgrWheelReport(
  direction: "up" | "down",
  col: number,
  row: number,
): string {
  const button = direction === "up" ? 64 : 65;
  return `\x1b[<${button};${Math.max(1, Math.round(col))};${Math.max(1, Math.round(row))}M`;
}

/**
 * A wheel event's movement in terminal lines (fractional). deltaMode 0 =
 * pixels, 1 = lines, 2 = pages — the same normalisation xterm.js applies
 * before it reports the wheel to a full-screen app.
 */
export function wheelDeltaToLines(
  deltaY: number,
  deltaMode: number,
  lineHeightPx: number,
  pageRows: number,
): number {
  if (deltaMode === 1) return deltaY;
  if (deltaMode === 2) return deltaY * Math.max(pageRows, 1);
  return lineHeightPx > 0 ? deltaY / lineHeightPx : 0;
}

/**
 * Collects wheel / swipe movement into whole lines: returns the signed number
 * of lines to report now (0 while under a line). Fractions carry over, and a
 * change of direction drops the leftover so the first step back isn't lost.
 */
export class WheelLines {
  #pending = 0;

  add(lines: number): number {
    if (!Number.isFinite(lines) || lines === 0) return 0;
    if (this.#pending !== 0 && Math.sign(this.#pending) !== Math.sign(lines)) {
      this.#pending = 0;
    }
    this.#pending += lines;
    const whole = Math.trunc(this.#pending);
    this.#pending -= whole;
    return whole;
  }

  reset(): void {
    this.#pending = 0;
  }
}

/**
 * `lines` wheel reports at one cell, as a single string, so the TUI receives
 * them together. Capped at `maxLines` (a screenful) so one huge delta can't
 * flood the PTY.
 */
export function sgrWheelReports(
  lines: number,
  col: number,
  row: number,
  maxLines: number,
): string {
  const count = Math.min(Math.abs(Math.trunc(lines)), Math.max(1, Math.trunc(maxLines)));
  if (!count) return "";
  return sgrWheelReport(lines < 0 ? "up" : "down", col, row).repeat(count);
}

/** 1-based terminal cell under a point, clamped to the grid. */
export function cellAtPoint(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
  cols: number,
  rows: number,
): { col: number; row: number } {
  const cellW = cols > 0 ? rect.width / cols : 0;
  const cellH = rows > 0 ? rect.height / rows : 0;
  const col = cellW > 0 ? Math.floor((clientX - rect.left) / cellW) + 1 : 1;
  const row = cellH > 0 ? Math.floor((clientY - rect.top) / cellH) + 1 : 1;
  return {
    col: Math.min(Math.max(col, 1), Math.max(cols, 1)),
    row: Math.min(Math.max(row, 1), Math.max(rows, 1)),
  };
}
