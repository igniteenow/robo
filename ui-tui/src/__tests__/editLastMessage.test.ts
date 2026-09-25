import { beforeEach, describe, expect, it, vi } from 'vitest'

import { EDIT_REWIND_RETRY_MS, rewindLastTurn, trimFromLastUser } from '../app/editLastMessage.js'
import { findSlashCommand } from '../app/slash/registry.js'
import { turnController } from '../app/turnController.js'
import { resetTurnState } from '../app/turnStore.js'
import { getUiState, patchUiState, resetUiState } from '../app/uiStore.js'
import type { Msg } from '../types.js'

const busyError = () => new Error('session busy — /interrupt the current turn before /undo')

const deps = (request: (method: string, params: Record<string, unknown>) => Promise<unknown>) => ({
  isBusyError: (e: unknown) => e instanceof Error && /session busy/.test(e.message),
  request,
  sleep: vi.fn(async () => {})
})

describe('trimFromLastUser', () => {
  it('drops the last user bubble and everything after it — partial reply, trails, the interrupted note', () => {
    const items: Msg[] = [
      { role: 'user', text: 'first' },
      { role: 'assistant', text: 'one' },
      { role: 'user', text: 'start the deploy' },
      { kind: 'trail', role: 'system', text: '', tools: ['terminal'] },
      { role: 'assistant', text: 'Deploying…\n\n*[interrupted]*' },
      { role: 'system', text: 'interrupted' }
    ]

    expect(trimFromLastUser(items)).toEqual([
      { role: 'user', text: 'first' },
      { role: 'assistant', text: 'one' }
    ])
  })

  it('goes back past the answer to a clarify question — that bubble is part of the exchange', () => {
    const items: Msg[] = [
      { role: 'user', text: 'first' },
      { role: 'assistant', text: 'one' },
      { role: 'user', text: 'set up the project' },
      { kind: 'trail', role: 'system', text: '', tools: ['clarify'] },
      { kind: 'clarify', role: 'user', text: 'python' },
      { role: 'assistant', text: 'Creating…' }
    ]

    expect(trimFromLastUser(items)).toEqual([
      { role: 'user', text: 'first' },
      { role: 'assistant', text: 'one' }
    ])
  })

  it('leaves a transcript without a user message untouched', () => {
    const items: Msg[] = [{ role: 'system', text: 'welcome' }]

    expect(trimFromLastUser(items)).toEqual(items)
  })
})

describe('rewindLastTurn', () => {
  it('returns the prefill the gateway hands back', async () => {
    const request = vi.fn(async () => ({ message: 'start the deploy', notice: '↶ Undid 1 turn', type: 'prefill' }))

    await expect(rewindLastTurn('sid-1', deps(request))).resolves.toEqual({
      message: 'start the deploy',
      notice: '↶ Undid 1 turn'
    })
    expect(request).toHaveBeenCalledWith('command.dispatch', { arg: '', name: 'undo', session_id: 'sid-1' })
  })

  it('retries only "session busy" while the interrupted turn unwinds, on the schedule', async () => {
    let calls = 0

    const request = vi.fn(async () => {
      calls += 1

      if (calls < 4) {
        throw busyError()
      }

      return { message: 'again', type: 'prefill' }
    })

    const d = deps(request)

    await expect(rewindLastTurn('sid', d)).resolves.toEqual({ message: 'again', notice: undefined })
    expect(d.sleep.mock.calls.map(call => call[0])).toEqual([...EDIT_REWIND_RETRY_MS.slice(0, 3)])
  })

  it('gives up after the schedule and surfaces the busy error', async () => {
    const request = vi.fn(async () => {
      throw busyError()
    })

    await expect(rewindLastTurn('sid', deps(request), [1, 1])).rejects.toThrow(/session busy/)
    expect(request).toHaveBeenCalledTimes(3)
  })

  it('does not retry other errors', async () => {
    const request = vi.fn(async () => {
      throw new Error('no user messages to undo')
    })

    await expect(rewindLastTurn('sid', deps(request))).rejects.toThrow(/no user messages/)
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('resolves null when the gateway answered with something other than a prefill', async () => {
    await expect(
      rewindLastTurn(
        'sid',
        deps(async () => ({ output: 'ok', type: 'exec' }))
      )
    ).resolves.toBeNull()
  })
})

describe('/edit slash command', () => {
  const ctx = () => {
    const request = vi.fn(async (method: string) =>
      method === 'command.dispatch' ? { message: 'start the deploy', notice: '↶ Undid 1 turn', type: 'prefill' } : {}
    )

    const history: Msg[] = [
      { role: 'user', text: 'start the deploy' },
      { role: 'assistant', text: 'Deploying…' }
    ]

    const shown: { items: Msg[] } = { items: history }

    return {
      composer: { queueRef: { current: [] as { display: string; text: string }[] }, setInput: vi.fn() },
      gateway: { gw: { request }, rpc: vi.fn(async () => null) },
      guardedErr: vi.fn(),
      shown,
      sid: 'sid-edit',
      transcript: {
        appendMessage: vi.fn(),
        setHistoryItems: vi.fn((updater: (prev: Msg[]) => Msg[]) => {
          shown.items = updater(shown.items)
        }),
        sys: vi.fn()
      }
    }
  }

  beforeEach(() => {
    resetUiState()
    resetTurnState()
    turnController.fullReset()
  })

  it('backs the session up, drops the old exchange, and puts the text in the composer under EDIT', async () => {
    const c = ctx()

    findSlashCommand('edit')!.run('', c as never, '/edit')

    await vi.waitFor(() => expect(c.composer.setInput).toHaveBeenCalledWith('start the deploy'))
    expect(c.shown.items).toEqual([])
    expect(getUiState().editingLast).toBe(true)
    // Idle: no interrupt was sent.
    expect(c.gateway.gw.request).not.toHaveBeenCalledWith('session.interrupt', expect.anything())
  })

  it('stops a running turn first', async () => {
    const c = ctx()

    patchUiState({ busy: true, sid: 'sid-edit' })
    findSlashCommand('edit')!.run('', c as never, '/edit')

    expect(c.gateway.gw.request).toHaveBeenCalledWith('session.interrupt', { session_id: 'sid-edit' })
    await vi.waitFor(() => expect(getUiState().editingLast).toBe(true))
  })

  it('refuses while messages are queued — they would go out the moment the turn stops', () => {
    const c = ctx()

    c.composer.queueRef.current.push({ display: 'then deploy', text: 'then deploy' })
    patchUiState({ busy: true, sid: 'sid-edit' })
    findSlashCommand('edit')!.run('', c as never, '/edit')

    expect(c.transcript.sys).toHaveBeenCalledTimes(1)
    expect(c.transcript.sys.mock.calls[0]![0]).toMatch(/1 queued message.*Ctrl\+X/)
    expect(c.gateway.gw.request).not.toHaveBeenCalled()
    expect(getUiState().editingLast).toBe(false)
  })

  it('says so when there is no session yet', () => {
    const c = { ...ctx(), sid: null }

    findSlashCommand('edit')!.run('', c as never, '/edit')

    expect(c.transcript.sys).toHaveBeenCalledWith('nothing to edit yet')
    expect(c.gateway.gw.request).not.toHaveBeenCalled()
  })
})
