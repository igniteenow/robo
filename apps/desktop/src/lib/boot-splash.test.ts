import { describe, expect, it } from 'vitest'

import { BOOT_SPLASH_ATTR, BOOT_SPLASH_ID, removeBootSplash } from './boot-splash'

describe('removeBootSplash', () => {
  it('takes the splash and its opt-in attribute down', () => {
    const splash = document.createElement('div')
    splash.id = BOOT_SPLASH_ID
    document.body.appendChild(splash)
    document.documentElement.setAttribute(BOOT_SPLASH_ATTR, '')

    removeBootSplash(document)

    expect(document.getElementById(BOOT_SPLASH_ID)).toBeNull()
    expect(document.documentElement.hasAttribute(BOOT_SPLASH_ATTR)).toBe(false)
  })

  it('is a no-op in a window that never showed one', () => {
    expect(() => removeBootSplash(document)).not.toThrow()
    expect(() => removeBootSplash(document)).not.toThrow()
  })
})
