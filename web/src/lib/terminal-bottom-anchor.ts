/**
 * Keep the embedded chat anchored to the bottom of its pane.
 *
 * The dashboard runs the TUI inline (primary buffer, so xterm's scrollback
 * holds history — see web_server's ROBO_TUI_INLINE). Inline, the TUI is only
 * as tall as its content: a new or short conversation drew the header and
 * the input box in the top half of the pane with empty space below, so the
 * chat box looked stranded in the middle of the page.
 *
 * Instead of touching the TUI, the browser shifts the terminal down by the
 * number of empty rows under the content, so the input box sits at the
 * bottom like any chat app. Once the conversation fills the pane (or there
 * is scrollback) the shift is 0 and nothing changes.
 */

export interface BottomAnchorBuffer {
  rows: number;
  /** Rows already in scrollback (xterm `buffer.active.baseY`). */
  baseY: number;
  /** Cursor row within the viewport (xterm `buffer.active.cursorY`). */
  cursorY: number;
  /** True when viewport row `y` has no text and no painted background. */
  lineIsBlank: (y: number) => boolean;
}

/** Number of empty rows to push the terminal down by (0 = no shift). */
export function bottomAnchorOffsetRows(buffer: BottomAnchorBuffer): number {
  const { rows, baseY } = buffer;
  if (!(rows > 0) || baseY > 0) {
    return 0;
  }

  const cursorRow = Math.min(Math.max(buffer.cursorY, 0), rows - 1);
  let lastUsedRow = cursorRow;
  for (let y = rows - 1; y > cursorRow; y--) {
    if (!buffer.lineIsBlank(y)) {
      lastUsedRow = y;
      break;
    }
  }

  return Math.max(0, rows - 1 - lastUsedRow);
}
