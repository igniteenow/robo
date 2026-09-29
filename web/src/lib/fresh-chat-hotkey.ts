/**
 * Idle Ctrl+C / Ctrl+D in the dashboard chat starts a fresh chat.
 *
 * The TUI (ROBO_TUI_DASHBOARD=1) answers an idle Ctrl+C / Ctrl+D by printing
 * FRESH_CHAT_NOTICE instead of exiting, and publishes a
 * `dashboard.new_session_requested` event for the sidebar. That event only
 * reaches the page while the TUI is attached to the dashboard's own gateway;
 * the chat now runs its own gateway (like `robo` in a terminal), so the page
 * watches the screen for a NEW notice right after the user presses the key.
 * A busy TUI (Ctrl+C interrupts the turn) or a non-empty composer (Ctrl+C
 * clears it) prints no notice, so nothing happens then.
 */

/** Text the TUI prints (useInputHandlers.ts DASHBOARD_NEW_SESSION_MESSAGE). */
export const FRESH_CHAT_NOTICE = "starting a fresh dashboard chat";

/** How long after the key press a new notice still counts. */
export const FRESH_CHAT_WATCH_MS = 2000;

/** Ctrl+C / Ctrl+D exactly as xterm.js emits them for a single key press. */
export function isIdleExitKey(data: string): boolean {
  return data === "\x03" || data === "\x04";
}

/** Occurrences of the notice on screen. Rows are joined and whitespace is
 * collapsed so a notice the TUI wrapped at a space still counts. */
export function countFreshChatNotices(rows: Iterable<string>): number {
  const text = Array.from(rows).join(" ").replace(/\s+/g, " ").toLowerCase();
  let count = 0;
  for (
    let at = text.indexOf(FRESH_CHAT_NOTICE);
    at !== -1;
    at = text.indexOf(FRESH_CHAT_NOTICE, at + FRESH_CHAT_NOTICE.length)
  ) {
    count += 1;
  }
  return count;
}

/**
 * Armed on an idle-exit key press with the notice count at that moment;
 * `seen` says whether the screen now shows one more (the TUI's answer).
 */
export class FreshChatHotkeyWatch {
  private baseline = 0;
  private until = 0;

  arm(noticesOnScreen: number, now: number): void {
    this.baseline = noticesOnScreen;
    this.until = now + FRESH_CHAT_WATCH_MS;
  }

  get armed(): boolean {
    return this.until > 0;
  }

  /** True once, when a new notice appeared inside the watch window. */
  seen(noticesOnScreen: number, now: number): boolean {
    if (this.until === 0) return false;
    if (now > this.until) {
      this.until = 0;
      return false;
    }
    if (noticesOnScreen <= this.baseline) return false;
    this.until = 0;
    return true;
  }
}
