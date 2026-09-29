/**
 * Which session the persistent dashboard chat is attached to.
 *
 * ChatPage stays mounted (hidden) on every dashboard route so the PTY
 * survives tab switches. It used to read `?resume=` straight from the
 * current URL — but on /sessions, /skills, … the URL has no `resume`, so
 * merely leaving the chat changed the PTY identity: the terminal was torn
 * down and a fresh agent booted in the background, and coming back showed a
 * blank chat (then a different conversation) instead of the one you left.
 *
 * The rule now: the resume target is sticky. It only changes while the chat
 * route is active and the URL names a different session, or when the person
 * explicitly starts a fresh chat. Other pages' URLs are ignored.
 */

export interface ChatResumeScope {
  /** Session the chat is attached to (null = a fresh chat). */
  resume: string | null;
  /**
   * Session a "new chat" just left. The URL still names it until the
   * navigation that removes `?resume=` commits; ignore it until then.
   */
  abandoned: string | null;
  lastUrlResume: string | null;
  lastActive: boolean;
}

export function initialChatResumeScope(
  isActive: boolean,
  urlResume: string | null,
): ChatResumeScope {
  return {
    resume: isActive ? urlResume : null,
    abandoned: null,
    lastUrlResume: urlResume,
    lastActive: isActive,
  };
}

/**
 * Fold the current route into the scope. Returns the SAME object when
 * nothing changed, so it is safe to call during render.
 */
export function nextChatResumeScope(
  scope: ChatResumeScope,
  isActive: boolean,
  urlResume: string | null,
): ChatResumeScope {
  if (scope.lastActive === isActive && scope.lastUrlResume === urlResume) {
    return scope;
  }

  const next: ChatResumeScope = {
    ...scope,
    lastActive: isActive,
    lastUrlResume: urlResume,
  };

  if (!isActive) {
    // Another page owns the URL — its (missing) `resume` means nothing here.
    return next;
  }

  if (urlResume === null) {
    // Bare /chat: keep the conversation we were in. The URL has also caught
    // up with any "new chat" request by now.
    next.abandoned = null;
    return next;
  }

  if (urlResume === scope.abandoned) {
    // Stale URL from just before "new chat" — don't jump back into it.
    return next;
  }

  next.resume = urlResume;
  next.abandoned = null;
  return next;
}

/** The person asked for a brand-new chat. */
export function startFreshChatResumeScope(
  scope: ChatResumeScope,
  urlResume: string | null,
): ChatResumeScope {
  return {
    ...scope,
    resume: null,
    abandoned: scope.resume ?? urlResume,
  };
}

/**
 * When /chat is shown without `?resume=` but the chat is attached to a
 * session, the id to put back in the URL (so a refresh reattaches to the
 * same conversation). Null when the URL is already right.
 */
export function resumeIdToRestoreInUrl(
  scope: ChatResumeScope,
  isActive: boolean,
  urlResume: string | null,
): string | null {
  if (!isActive || !scope.resume || urlResume !== null) {
    return null;
  }
  return scope.resume;
}
