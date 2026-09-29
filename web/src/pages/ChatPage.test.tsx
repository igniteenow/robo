// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  MemoryRouter,
  type NavigateFunction,
  useLocation,
  useNavigate,
} from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

class FakeFitAddon {
  fit() {}
}

class FakeWebglAddon {
  onContextLoss() {
    return { dispose() {} };
  }
}

class FakeTerminal {
  options: Record<string, unknown>;
  rows = 24;
  cols = 80;
  buffer = { active: { type: "normal" } };
  parser = {
    registerOscHandler: vi.fn(),
  };
  unicode = { activeVersion: "" };

  constructor(options: Record<string, unknown>) {
    this.options = options;
  }

  attachCustomKeyEventHandler() {
    return true;
  }

  attachCustomWheelEventHandler() {
    return true;
  }

  clearSelection() {}

  dispose() {}

  focus() {}

  getSelection() {
    return "";
  }

  loadAddon() {}

  onData() {
    return { dispose() {} };
  }

  onResize() {
    return { dispose() {} };
  }

  onWriteParsed() {
    return { dispose() {} };
  }

  open() {}

  paste() {}

  refresh() {}

  write() {}
}

const maybeReloadForLoopbackWsAuthFailure = vi.fn(() => false);

vi.mock("@xterm/addon-fit", () => ({ FitAddon: FakeFitAddon }));
vi.mock("@xterm/addon-unicode11", () => ({ Unicode11Addon: class {} }));
vi.mock("@xterm/addon-web-links", () => ({ WebLinksAddon: class {} }));
vi.mock("@xterm/addon-webgl", () => ({ WebglAddon: FakeWebglAddon }));
vi.mock("@xterm/xterm", () => ({ Terminal: FakeTerminal }));
vi.mock("@/components/ChatSidebar", () => ({
  ChatSidebar: () => null,
}));
vi.mock("@/components/ChatSessionList", () => ({
  ChatSessionList: () => null,
}));
vi.mock("@/components/Backdrop", () => ({ Backdrop: () => null }));
vi.mock("@/plugins", () => ({
  PluginSlot: () => null,
}));
const headerSetEnd = vi.fn();
vi.mock("@/contexts/usePageHeader", () => ({
  usePageHeader: () => ({ setEnd: headerSetEnd, setTitle: vi.fn() }),
}));
vi.mock("@/contexts/useProfileScope", () => ({
  useProfileScope: () => ({ profile: "" }),
}));
vi.mock("@/themes", () => ({
  useTheme: () => ({ theme: { terminalBackground: "#000000" } }),
}));
vi.mock("@/i18n", () => ({
  useI18n: () => ({
    t: {
      app: {
        closeModelTools: "Close model tools",
        modelToolsSheetSubtitle: "Tools",
        modelToolsSheetTitle: "Model",
      },
    },
  }),
}));
vi.mock("@/lib/dashboard-auth-reload", () => ({
  maybeReloadForLoopbackWsAuthFailure,
}));

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;

  binaryType = "blob";
  onclose: ((event: CloseEventLike) => void) | null = null;
  onmessage: ((event: { data: ArrayBuffer | string }) => void) | null = null;
  onopen: (() => void) | null = null;
  readyState = FakeWebSocket.OPEN;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.readyState = 3;
  }

  send() {}
}

type CloseEventLike = {
  code: number;
  reason: string;
  wasClean: boolean;
};

let container: HTMLDivElement;
let root: Root;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(ui));
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  maybeReloadForLoopbackWsAuthFailure.mockClear();
  headerSetEnd.mockClear();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      disconnect() {}
      observe() {}
      unobserve() {}
    },
  );
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(0);
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  vi.stubGlobal("matchMedia", () => ({
    addEventListener() {},
    matches: false,
    media: "",
    removeEventListener() {},
  }));
  vi.stubGlobal("crypto", {
    getRandomValues: (values: Uint8Array) => {
      values.fill(7);
      return values;
    },
    randomUUID: () => "chat-test-id",
  });

  Object.defineProperty(window, "visualViewport", {
    configurable: true,
    value: { addEventListener() {}, removeEventListener() {}, width: 1280 },
  });
  Object.defineProperty(window, "__ROBO_SESSION_TOKEN__", {
    configurable: true,
    value: "stale-token",
    writable: true,
  });
  Object.defineProperty(window, "__ROBO_AUTH_REQUIRED__", {
    configurable: true,
    value: false,
    writable: true,
  });
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: {
      readText: vi.fn(async () => ""),
      writeText: vi.fn(async () => {}),
    },
  });
  sessionStorage.clear();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.unstubAllGlobals();
});

describe("ChatPage", () => {
  it("treats loopback 4401 closes as stale-token reload candidates", async () => {
    const { default: ChatPage } = await import("./ChatPage");

    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );

    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    FakeWebSocket.instances[0].onclose?.({
      code: 4401,
      reason: "auth: token_mismatch",
      wasClean: true,
    });

    expect(maybeReloadForLoopbackWsAuthFailure).toHaveBeenCalledWith(4401);
  });

  it("puts its actions in the page header and only clears its own", async () => {
    const { default: ChatPage } = await import("./ChatPage");

    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );

    const placed = headerSetEnd.mock.calls
      .map(([arg]) => arg)
      .filter((arg) => typeof arg !== "function");
    expect(placed.length).toBeGreaterThan(0);
    const ours = placed[placed.length - 1];
    expect(ours).toBeTruthy();

    await act(async () => root.unmount());

    const clear = headerSetEnd.mock.calls
      .map(([arg]) => arg)
      .filter((arg): arg is (current: unknown) => unknown => typeof arg === "function")
      .pop();
    expect(clear).toBeDefined();
    // Still ours → removed. Another page's buttons → left alone.
    expect(clear?.(ours)).toBeNull();
    const otherPage = { page: "cron" };
    expect(clear?.(otherPage)).toBe(otherPage);

    // afterEach unmounts again; give it a fresh root.
    root = createRoot(container);
  });

  it("keeps the resumed chat alive while other dashboard pages are open", async () => {
    const { default: ChatPage } = await import("./ChatPage");
    const nav: { current: NavigateFunction | null } = { current: null };

    // Mirrors App.tsx: one persistent ChatPage, active only on /chat.
    function PersistentChatHost() {
      const location = useLocation();
      nav.current = useNavigate();
      return <ChatPage isActive={location.pathname === "/chat"} />;
    }

    await render(
      <MemoryRouter initialEntries={["/chat?resume=sess-a"]}>
        <PersistentChatHost />
      </MemoryRouter>,
    );

    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(FakeWebSocket.instances[0].url).toContain("resume=sess-a");

    // /sessions has no ?resume= — that must not tear the terminal down or
    // boot a different agent in the background.
    await act(async () => {
      await nav.current?.("/sessions");
    });
    // Back through the bare nav link.
    await act(async () => {
      await nav.current?.("/chat");
    });

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].readyState).toBe(FakeWebSocket.OPEN);
  });

  it("keeps every chat opened from history connected (not every other one)", async () => {
    const { default: ChatPage } = await import("./ChatPage");
    const nav: { current: NavigateFunction | null } = { current: null };

    function PersistentChatHost() {
      const location = useLocation();
      nav.current = useNavigate();
      return <ChatPage isActive={location.pathname === "/chat"} />;
    }

    await render(
      <MemoryRouter initialEntries={["/chat?resume=sess-a"]}>
        <PersistentChatHost />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const chatA = FakeWebSocket.instances[0];

    // Open chat B from the session list.
    await act(async () => {
      await nav.current?.("/chat?resume=sess-b");
    });
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    const chatB = FakeWebSocket.instances[1];
    expect(chatB.url).toContain("resume=sess-b");
    expect(chatA.readyState).toBe(3);

    // Chat A's close completes only now, after B is connected. It must not
    // cut B off: a window focus must leave B alone, not reload the chat.
    await act(async () => {
      chatA.onclose?.({ code: 1005, reason: "", wasClean: true });
    });
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    // Open chat C: B's socket is closed (it used to be leaked, and the chat
    // after it froze in turn).
    await act(async () => {
      await nav.current?.("/chat?resume=sess-c");
    });
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(3));
    expect(chatB.readyState).toBe(3);
    expect(FakeWebSocket.instances[2].readyState).toBe(FakeWebSocket.OPEN);
  });
});
