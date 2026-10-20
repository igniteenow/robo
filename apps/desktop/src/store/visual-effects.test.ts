import { afterEach, describe, expect, it } from 'vitest'

import {
  $softwareRendering,
  $softwareRenderingReason,
  $visualEffects,
  $visualEffectsPreference,
  adoptRenderingInfo,
  applyVisualEffects,
  isVisualEffectsPreference,
  reducedEffects,
  resolveVisualEffects,
  setVisualEffectsPreference
} from './visual-effects'

afterEach(() => {
  $visualEffectsPreference.set('auto')
  $softwareRendering.set(false)
  $softwareRenderingReason.set(null)
})

describe('resolveVisualEffects', () => {
  it('auto follows the compositor; a pinned choice ignores it', () => {
    expect(resolveVisualEffects('auto', false)).toBe('full')
    expect(resolveVisualEffects('auto', true)).toBe('reduced')
    expect(resolveVisualEffects('full', true)).toBe('full')
    expect(resolveVisualEffects('reduced', false)).toBe('reduced')
  })
})

describe('the level in force', () => {
  it('lands on <html data-effects> the moment it changes', () => {
    setVisualEffectsPreference('reduced')
    expect(document.documentElement.dataset.effects).toBe('reduced')
    expect(reducedEffects()).toBe(true)

    setVisualEffectsPreference('full')
    expect(document.documentElement.dataset.effects).toBeUndefined()
    expect(reducedEffects()).toBe(false)
  })

  it("follows Electron's report under auto, and remembers why", () => {
    setVisualEffectsPreference('auto')
    adoptRenderingInfo({ software: true, reason: 'remote display: rdp' })

    expect($visualEffects.get()).toBe('reduced')
    expect($softwareRenderingReason.get()).toBe('remote display: rdp')
    expect(document.documentElement.dataset.effects).toBe('reduced')

    adoptRenderingInfo({ software: false, reason: null })
    expect($visualEffects.get()).toBe('full')
    expect($softwareRenderingReason.get()).toBeNull()
  })

  it('ignores a malformed report rather than flipping the level', () => {
    setVisualEffectsPreference('auto')
    adoptRenderingInfo({ software: true, reason: 'vm' })
    adoptRenderingInfo(null)
    adoptRenderingInfo(undefined)

    expect($visualEffects.get()).toBe('reduced')

    // A report whose `software` is not literally true reads as GPU-composited.
    adoptRenderingInfo({ software: 'yes', reason: 42 })
    expect($visualEffects.get()).toBe('full')
    expect($softwareRenderingReason.get()).toBeNull()
  })
})

describe('applyVisualEffects', () => {
  it('marks reduced, and drops the attribute entirely for full', () => {
    const root = { dataset: {} as DOMStringMap }

    applyVisualEffects('reduced', root)
    expect(root.dataset.effects).toBe('reduced')

    applyVisualEffects('full', root)
    expect(root.dataset.effects).toBeUndefined()
    expect('effects' in root.dataset).toBe(false)
  })
})

describe('isVisualEffectsPreference', () => {
  it('accepts the three levels and nothing else', () => {
    expect(isVisualEffectsPreference('auto')).toBe(true)
    expect(isVisualEffectsPreference('reduced')).toBe(true)
    expect(isVisualEffectsPreference('full')).toBe(true)
    expect(isVisualEffectsPreference('off')).toBe(false)
    expect(isVisualEffectsPreference(null)).toBe(false)
  })
})
