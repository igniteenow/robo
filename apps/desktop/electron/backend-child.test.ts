/**
 * Tests for releaseBackendsForUpdate in electron/backend-child.ts.
 *
 * Run with: npx vitest run --project electron electron/backend-child.test.ts
 *
 * Why this matters: before an update the app stops its backends and waits for
 * the venv's robo.exe to be free. It used to SIGTERM the backend first, which
 * on Windows kills only the direct child. For a backend started through
 * robo.cmd that is cmd.exe, so robo.exe and its python were orphaned, the
 * later `taskkill /T` found no parent to walk from, and every update from the
 * desktop timed out with "another process is holding the Robo install open".
 */

import assert from 'node:assert/strict'

import { test } from 'vitest'

import { releaseBackendsForUpdate } from './backend-child'

function fakeClock() {
  let now = 0

  return {
    now: () => now,
    sleep: async (ms: number) => {
      now += ms
    }
  }
}

test('each backend tree is killed while the backend is still alive, before anything else', async () => {
  const events: string[] = []
  const clock = fakeClock()

  const unlocked = await releaseBackendsForUpdate({
    ...clock,
    backendPids: () => [101, 202],
    forceKillProcessTree: pid => events.push(`tree-kill ${pid}`),
    isShimLocked: () => false,
    stopPoolBackends: () => events.push('stop pool')
  })

  assert.equal(unlocked, true)
  assert.deepEqual(events.slice(0, 2), ['tree-kill 101', 'tree-kill 202'])
})

test('it keeps killing backends that appear until the shim is free', async () => {
  const killed: number[] = []
  const clock = fakeClock()
  let checks = 0
  let pids = [101]

  const unlocked = await releaseBackendsForUpdate({
    ...clock,
    backendPids: () => pids,
    forceKillProcessTree: pid => {
      killed.push(pid)
      pids = []
    },
    isShimLocked: () => {
      checks += 1

      if (checks === 1) {
        pids = [303] // a pool backend registered mid-teardown

        return true
      }

      return false
    },
    stopPoolBackends: () => undefined
  })

  assert.equal(unlocked, true)
  assert.deepEqual(killed, [101, 303])
})

test('it gives up when something outside the app still holds the shim', async () => {
  const clock = fakeClock()

  const unlocked = await releaseBackendsForUpdate({
    ...clock,
    backendPids: () => [],
    forceKillProcessTree: () => undefined,
    isShimLocked: () => true,
    pollMs: 300,
    stopPoolBackends: () => undefined,
    timeoutMs: 1_500
  })

  assert.equal(unlocked, false)
  assert.ok(clock.now() >= 1_500)
})
