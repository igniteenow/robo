/**
 * backend-child.ts
 *
 * Windows-aware teardown for the desktop's managed backend child process.
 *
 * Node's `child.kill()` only signals the direct child. On Windows a backend
 * that spawned its own grandchildren (a `robo` REPL, a pty terminal
 * session, the gateway) survives a plain SIGTERM and keeps files (e.g. the
 * venv shim) locked. So on Windows we tree-kill via `forceKillProcessTree`;
 * everywhere else a plain SIGTERM is correct and sufficient (POSIX has no
 * mandatory locks, and the backend is not spawned detached so there's no
 * process-group to negative-pid-kill).
 *
 * Extracted into its own dependency-free module (no electron import) so the
 * SIGTERM-vs-tree-kill branching can be asserted directly with a fake child
 * object and a spy `forceKillProcessTree`, instead of grepping main.ts source
 * text for the function body.
 */

export interface StopBackendChildDeps {
  /** Defaults to the real platform check; injectable for tests. */
  isWindows?: boolean
  /** Windows tree-kill implementation (real: taskkill /T /F via execFileSync). */
  forceKillProcessTree: (pid: number) => void
}

export interface KillableChild {
  pid?: number | null
  killed?: boolean
  kill: (signal: string) => void
}

/**
 * Stop a managed child process, choosing the right strategy for the platform.
 * No-ops silently if `child` is falsy, already killed, or the kill attempt
 * throws (the process may already be gone) -- mirrors the original inline
 * best-effort semantics in main.ts.
 */
export function stopBackendChild(child: KillableChild | null | undefined, deps: StopBackendChildDeps) {
  if (!child || child.killed) {
    return
  }

  const isWindows = deps.isWindows ?? process.platform === 'win32'

  try {
    if (isWindows && Number.isInteger(child.pid)) {
      deps.forceKillProcessTree(child.pid as number)
    } else {
      child.kill('SIGTERM')
    }
  } catch {
    // Already gone.
  }
}

export interface ReleaseBackendsDeps {
  /** Pids of every backend the app runs right now (primary + pool). Re-read on each pass. */
  backendPids: () => number[]
  /** Stop and forget the pool backends (profiles other than the window's). */
  stopPoolBackends: () => void
  /** Windows tree-kill (real: taskkill /T /F). */
  forceKillProcessTree: (pid: number) => void
  /** True while a live process still holds the venv's robo.exe. */
  isShimLocked: () => boolean
  sleep: (ms: number) => Promise<void>
  now: () => number
  timeoutMs?: number
  pollMs?: number
}

/**
 * Stop every backend the app owns and wait until the venv's robo.exe is free,
 * so an update can replace it. Resolves to whether it came free in time.
 *
 * Each backend's whole process tree is killed while the backend itself is
 * still alive: `taskkill /T` finds descendants through their parent, so the
 * parent has to be there. A SIGTERM first (on Windows that is TerminateProcess
 * of the direct child only, not a graceful stop) killed just the wrapper -- for
 * a backend started through `robo.cmd`, cmd.exe -- and orphaned robo.exe and
 * its python, which then held the shim until the update gave up.
 */
export async function releaseBackendsForUpdate(deps: ReleaseBackendsDeps): Promise<boolean> {
  const timeoutMs = deps.timeoutMs ?? 15_000
  const pollMs = deps.pollMs ?? 300

  for (const pid of deps.backendPids()) {
    deps.forceKillProcessTree(pid)
  }

  deps.stopPoolBackends()
  const deadline = deps.now() + timeoutMs

  while (deps.now() < deadline) {
    if (!deps.isShimLocked()) {
      return true
    }

    // A backend registered mid-teardown (a pool entry, a respawn) is killed
    // on the next pass instead of trusting the first sweep.
    for (const pid of deps.backendPids()) {
      deps.forceKillProcessTree(pid)
    }

    await deps.sleep(pollMs)
  }

  return !deps.isShimLocked()
}
