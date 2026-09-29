import { describe, expect, it } from "vitest";

import {
  initialChatResumeScope,
  nextChatResumeScope,
  resumeIdToRestoreInUrl,
  startFreshChatResumeScope,
} from "./chat-resume-scope";

describe("chat resume scope", () => {
  it("keeps the resumed session while other dashboard pages are open", () => {
    let scope = initialChatResumeScope(true, "sess-a");
    expect(scope.resume).toBe("sess-a");

    // /sessions, /skills … have no ?resume= — the chat must not change.
    scope = nextChatResumeScope(scope, false, null);
    expect(scope.resume).toBe("sess-a");

    // Back to bare /chat via the nav link: still the same conversation.
    scope = nextChatResumeScope(scope, true, null);
    expect(scope.resume).toBe("sess-a");
    expect(resumeIdToRestoreInUrl(scope, true, null)).toBe("sess-a");
  });

  it("ignores ?resume= on other pages", () => {
    let scope = initialChatResumeScope(true, null);
    scope = nextChatResumeScope(scope, false, "sess-from-another-page");
    expect(scope.resume).toBeNull();
  });

  it("switches when /chat is opened for a different session", () => {
    let scope = initialChatResumeScope(true, "sess-a");
    scope = nextChatResumeScope(scope, false, null);
    scope = nextChatResumeScope(scope, true, "sess-b");
    expect(scope.resume).toBe("sess-b");
    expect(resumeIdToRestoreInUrl(scope, true, "sess-b")).toBeNull();
  });

  it("a new chat does not bounce back to the old session while the URL catches up", () => {
    let scope = initialChatResumeScope(true, "sess-a");
    scope = startFreshChatResumeScope(scope, "sess-a");
    expect(scope.resume).toBeNull();

    // The URL still says sess-a for a moment…
    scope = nextChatResumeScope(scope, true, "sess-a");
    expect(scope.resume).toBeNull();
    // …then the navigation commits.
    scope = nextChatResumeScope(scope, true, null);
    expect(scope.resume).toBeNull();
    expect(resumeIdToRestoreInUrl(scope, true, null)).toBeNull();

    // Opening sess-a again later is an explicit request and works.
    scope = nextChatResumeScope(scope, true, "sess-a");
    expect(scope.resume).toBe("sess-a");
  });

  it("returns the same object when nothing changed (safe during render)", () => {
    const scope = initialChatResumeScope(true, "sess-a");
    expect(nextChatResumeScope(scope, true, "sess-a")).toBe(scope);
  });

  it("does not restore the URL while hidden", () => {
    const scope = initialChatResumeScope(true, "sess-a");
    expect(resumeIdToRestoreInUrl(scope, false, null)).toBeNull();
  });

  it("a chat mounted behind another page starts fresh", () => {
    expect(initialChatResumeScope(false, "x").resume).toBeNull();
  });
});
