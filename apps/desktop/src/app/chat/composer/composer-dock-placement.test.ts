import { describe, expect, it } from 'vitest'

import { composerDockPlacementClass } from './composer-utils'

// A fresh, empty chat opens with the composer in the middle of the chat zone;
// the first message sends it to the bottom, where it stays. Floating keeps
// its own (fixed) placement whatever the chat looks like.

describe('composerDockPlacementClass', () => {
  it('centers a fresh chat and docks a conversation at the bottom', () => {
    const centered = composerDockPlacementClass(false, true)
    const docked = composerDockPlacementClass(false, false)

    expect(centered).toContain('top-1/2')
    expect(centered).toContain('-translate-y-1/2')
    expect(centered).not.toContain('bottom-0')

    expect(docked).toContain('bottom-0')
    expect(docked).not.toContain('top-1/2')

    for (const placement of [centered, docked]) {
      expect(placement).toContain('absolute')
      expect(placement).toContain('left-1/2')
      expect(placement).toContain('-translate-x-1/2')
    }
  })

  it('leaves a popped-out composer alone', () => {
    expect(composerDockPlacementClass(true, true)).toBe(composerDockPlacementClass(true, false))
    expect(composerDockPlacementClass(true, true)).toContain('fixed')
  })
})
