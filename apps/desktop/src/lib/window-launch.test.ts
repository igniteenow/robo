import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  _resetFreshWindowLaunchForTests,
  isFreshWindowLaunch,
  markWindowBooted,
  peekFreshWindowLaunch
} from './window-launch'

describe('isFreshWindowLaunch', () => {
  beforeEach(() => {
    sessionStorage.clear()
    _resetFreshWindowLaunchForTests()
  })

  afterEach(() => {
    sessionStorage.clear()
    _resetFreshWindowLaunchForTests()
  })

  it('is a launch when this window has never booted, and latches for the page load', () => {
    expect(isFreshWindowLaunch()).toBe(true)
    // Later reads in the same page load keep the boot-time answer.
    expect(isFreshWindowLaunch()).toBe(true)
  })

  it('is a reload once the same window has booted before', () => {
    expect(isFreshWindowLaunch()).toBe(true)

    // A reload re-runs the module (a fresh latch) but keeps the window's
    // sessionStorage.
    _resetFreshWindowLaunchForTests()

    expect(isFreshWindowLaunch()).toBe(false)
  })

  it('never touches localStorage', () => {
    localStorage.setItem('kept', 'yes')

    isFreshWindowLaunch()

    expect(localStorage.getItem('kept')).toBe('yes')
    localStorage.removeItem('kept')
  })

  it('falls back to the reload behaviour when there is no usable sessionStorage', () => {
    const denied = {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('denied')
      }
    }

    expect(markWindowBooted(null)).toBe(false)
    expect(markWindowBooted(undefined)).toBe(false)
    expect(markWindowBooted(denied)).toBe(false)
  })

  it('marks the window on first read only', () => {
    const store = new Map<string, string>()

    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value)
    }

    expect(markWindowBooted(storage)).toBe(true)
    expect(markWindowBooted(storage)).toBe(false)
  })
})

describe('peekFreshWindowLaunch', () => {
  beforeEach(() => {
    sessionStorage.clear()
    _resetFreshWindowLaunchForTests()
  })

  afterEach(() => {
    sessionStorage.clear()
    _resetFreshWindowLaunchForTests()
  })

  it('answers without marking the window, so a reload before the restore acts is still a launch', () => {
    expect(peekFreshWindowLaunch()).toBe(true)
    expect(peekFreshWindowLaunch()).toBe(true)

    _resetFreshWindowLaunchForTests()

    expect(isFreshWindowLaunch()).toBe(true)
  })

  it('agrees with the latched decision once one is made', () => {
    expect(isFreshWindowLaunch()).toBe(true)
    expect(peekFreshWindowLaunch()).toBe(true)

    _resetFreshWindowLaunchForTests()

    expect(peekFreshWindowLaunch()).toBe(false)
    expect(isFreshWindowLaunch()).toBe(false)
  })
})
