import { beforeEach, describe, expect, it, vi } from 'vitest'

// The draft store decides at module init, so each case re-imports it into a
// window set up the way Electron hands it over: localStorage carried across
// runs, sessionStorage empty on a launch and marked on a reload.
const DRAFTS_KEY = 'robo:composer-drafts:v3'
const BOOTED_KEY = 'robo.desktop.window-booted'

describe('composer drafts on a fresh launch', () => {
  beforeEach(() => {
    vi.resetModules()
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('drops the new-chat draft, keeps chat drafts, and mirrors that to storage at once', async () => {
    window.localStorage.setItem(DRAFTS_KEY, JSON.stringify({ __new__: 'left in the box', 'session-a': 'kept' }))

    const composer = await import('./composer')

    expect(composer.takeSessionDraft(null).text).toBe('')
    expect(composer.takeSessionDraft('session-a').text).toBe('kept')
    expect(JSON.parse(window.localStorage.getItem(DRAFTS_KEY) ?? '{}')).toEqual({ 'session-a': 'kept' })
    // Marking the window as booted is the route restore's job, not the store's.
    expect(window.sessionStorage.getItem(BOOTED_KEY)).toBeNull()
  })

  it('keeps the new-chat draft across a reload of the same window', async () => {
    window.sessionStorage.setItem(BOOTED_KEY, '1')
    window.localStorage.setItem(DRAFTS_KEY, JSON.stringify({ __new__: 'still here' }))

    const composer = await import('./composer')

    expect(composer.takeSessionDraft(null).text).toBe('still here')
    expect(JSON.parse(window.localStorage.getItem(DRAFTS_KEY) ?? '{}')).toEqual({ __new__: 'still here' })
  })

  it('leaves storage alone when there was nothing to drop', async () => {
    window.localStorage.setItem(DRAFTS_KEY, JSON.stringify({ 'session-a': 'kept' }))

    await import('./composer')

    expect(JSON.parse(window.localStorage.getItem(DRAFTS_KEY) ?? '{}')).toEqual({ 'session-a': 'kept' })
  })
})
