import { describe, expect, it } from "vitest";

import {
  FRESH_CHAT_WATCH_MS,
  FreshChatHotkeyWatch,
  countFreshChatNotices,
  isIdleExitKey,
} from "./fresh-chat-hotkey";

describe("isIdleExitKey", () => {
  it("matches a single Ctrl+C or Ctrl+D press only", () => {
    expect(isIdleExitKey("\x03")).toBe(true);
    expect(isIdleExitKey("\x04")).toBe(true);
    expect(isIdleExitKey("c")).toBe(false);
    expect(isIdleExitKey("\x03\x03")).toBe(false);
    expect(isIdleExitKey("\x1b[<64;1;1M")).toBe(false);
  });
});

describe("countFreshChatNotices", () => {
  it("counts every notice on screen", () => {
    expect(countFreshChatNotices(["hello", "  starting a fresh dashboard chat..."])).toBe(1);
    expect(
      countFreshChatNotices([
        "starting a fresh dashboard chat...",
        "x",
        "starting a fresh dashboard chat...",
      ]),
    ).toBe(2);
    expect(countFreshChatNotices(["nothing here"])).toBe(0);
  });

  it("still counts a notice wrapped across rows at a space", () => {
    expect(countFreshChatNotices(["starting a fresh    ", "dashboard chat..."])).toBe(1);
  });
});

describe("FreshChatHotkeyWatch", () => {
  it("fires once when a new notice appears after the key press", () => {
    const watch = new FreshChatHotkeyWatch();
    watch.arm(1, 1000);
    expect(watch.seen(1, 1100)).toBe(false);
    expect(watch.seen(2, 1200)).toBe(true);
    expect(watch.seen(3, 1300)).toBe(false);
    expect(watch.armed).toBe(false);
  });

  it("ignores a notice that was already on screen", () => {
    const watch = new FreshChatHotkeyWatch();
    watch.arm(1, 0);
    expect(watch.seen(1, 500)).toBe(false);
  });

  it("gives up after the watch window (busy TUI or typed text)", () => {
    const watch = new FreshChatHotkeyWatch();
    watch.arm(0, 0);
    expect(watch.seen(1, FRESH_CHAT_WATCH_MS + 1)).toBe(false);
    expect(watch.armed).toBe(false);
  });

  it("never fires unarmed", () => {
    expect(new FreshChatHotkeyWatch().seen(5, 0)).toBe(false);
  });
});
