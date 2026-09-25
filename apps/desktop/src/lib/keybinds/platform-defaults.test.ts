import { afterEach, describe, expect, it, vi } from 'vitest'

// `IS_MAC` is resolved once at module load, so each platform case overrides
// `navigator.platform` and re-imports the actions module fresh.
async function loadActions(platform: string) {
  Object.defineProperty(window.navigator, 'platform', { value: platform, configurable: true })
  vi.resetModules()

  return import('./actions')
}

function defaultsOf(actions: Awaited<ReturnType<typeof loadActions>>, id: string): readonly string[] {
  return actions.KEYBIND_ACTIONS.find(a => a.id === id)?.defaults ?? []
}

afterEach(() => {
  vi.resetModules()
})

// Off macOS `ctrl` folds to `mod`, so a `ctrl+N` default would collide with the
// profiles' `mod+N` (which win: they come first in the index) and the voice
// toggle's `ctrl+b` with the sidebar's `mod+b`. Those rows ship on Alt there.
describe('platform-specific keybind defaults', () => {
  it('keeps ⌃1…⌃9 and ⌃B on macOS, where Control is distinct from Cmd', async () => {
    const actions = await loadActions('MacIntel')

    expect(defaultsOf(actions, 'session.slot.1')).toEqual(['ctrl+1'])
    expect(defaultsOf(actions, 'session.slot.9')).toEqual(['ctrl+9'])
    expect(defaultsOf(actions, 'composer.voice')).toEqual(['ctrl+b'])
  })

  it('ships Alt+1…9 and Alt+B off macOS so nothing collides with the profile / sidebar chords', async () => {
    const actions = await loadActions('Win32')
    const { canonicalizeCombo } = await import('./combo')
    const taken = new Set<string>()
    const collisions: string[] = []

    for (const action of actions.KEYBIND_ACTIONS) {
      for (const combo of action.defaults) {
        const key = canonicalizeCombo(combo)

        if (taken.has(key)) {
          collisions.push(`${action.id} → ${key}`)
        }

        taken.add(key)
      }
    }

    expect(defaultsOf(actions, 'session.slot.1')).toEqual(['alt+1'])
    expect(defaultsOf(actions, 'session.slot.9')).toEqual(['alt+9'])
    expect(defaultsOf(actions, 'composer.voice')).toEqual(['alt+b'])
    expect(defaultsOf(actions, 'profile.switch.1')).toEqual(['mod+1'])
    expect(defaultsOf(actions, 'view.toggleSidebar')).toEqual(['mod+b'])
    expect(collisions).toEqual([])
  })
})
