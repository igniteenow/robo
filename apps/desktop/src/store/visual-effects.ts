/**
 * Visual effects level: the blur-behind surfaces (composer glass, menus,
 * dialogs, the settings backdrop) and the slower exit choreography are a
 * `full` / `reduced` switch on `<html data-effects>`; styles.css carries the
 * reduced rules.
 *
 * Why it exists: `backdrop-filter` is composited per frame over everything
 * beneath it. With GPU compositing that is free; when Chromium composites on
 * the CPU — a server reached over RDP, a VM, a blocklisted driver — every
 * frame pays a full blur of the covered area, and the app crawls. Electron
 * knows which case it is (`getRenderingInfo`), so `auto` follows that and the
 * user can pin either level from Settings → Appearance.
 *
 * The last answer from Electron is remembered, so the first frames of the next
 * launch are already right instead of flashing full effects before the reply
 * arrives. The renderer owns the preference; Electron owns the machine fact.
 */

import { atom, computed } from 'nanostores'

import { persistBoolean, persistString, storedBoolean, storedString } from '@/lib/storage'

export type VisualEffectsPreference = 'auto' | 'full' | 'reduced'
export type VisualEffectsLevel = 'full' | 'reduced'

const PREFERENCE_KEY = 'robo.desktop.visual-effects.v1'
const SOFTWARE_RENDERING_KEY = 'robo.desktop.software-rendering.v1'

export const VISUAL_EFFECTS_PREFERENCES: readonly VisualEffectsPreference[] = ['auto', 'reduced', 'full']

export function isVisualEffectsPreference(value: unknown): value is VisualEffectsPreference {
  return typeof value === 'string' && (VISUAL_EFFECTS_PREFERENCES as readonly string[]).includes(value)
}

function readPreference(): VisualEffectsPreference {
  const stored = storedString(PREFERENCE_KEY)

  return isVisualEffectsPreference(stored) ? stored : 'auto'
}

/** The user's choice. `auto` = reduced while frames are composited in software. */
export const $visualEffectsPreference = atom<VisualEffectsPreference>(
  typeof window === 'undefined' ? 'auto' : readPreference()
)

/** Electron's answer: true while Chromium composites on the CPU. Seeded from
 *  the previous launch so the first paint already matches. */
export const $softwareRendering = atom<boolean>(
  typeof window === 'undefined' ? false : storedBoolean(SOFTWARE_RENDERING_KEY, false)
)

/** Why rendering is software, in Electron's words (About / diagnostics only). */
export const $softwareRenderingReason = atom<string | null>(null)

/** Pure: what the preference and the machine fact add up to. */
export function resolveVisualEffects(preference: VisualEffectsPreference, software: boolean): VisualEffectsLevel {
  if (preference === 'auto') {
    return software ? 'reduced' : 'full'
  }

  return preference
}

/** The level in force: what styles.css reads from `<html data-effects>`. */
export const $visualEffects = computed([$visualEffectsPreference, $softwareRendering], resolveVisualEffects)

/** True while blur-behind effects and exit choreography are switched off. */
export function reducedEffects(): boolean {
  return $visualEffects.get() === 'reduced'
}

export function setVisualEffectsPreference(preference: VisualEffectsPreference): void {
  $visualEffectsPreference.set(preference)
}

/** Mirror the level onto the root element; the stylesheet does the rest.
 *  `full` removes the attribute rather than writing `full`: the reduced rules
 *  start with `html[data-effects='reduced'] *`, and an absent attribute lets
 *  the style engine reject them for every element without walking up. */
export function applyVisualEffects(level: VisualEffectsLevel, root: { dataset: DOMStringMap }): void {
  if (level === 'reduced') {
    if (root.dataset.effects !== 'reduced') {
      root.dataset.effects = 'reduced'
    }
  } else if (root.dataset.effects !== undefined) {
    delete root.dataset.effects
  }
}

export interface RenderingInfoLike {
  software?: unknown
  reason?: unknown
}

/** Adopt Electron's report (also exported so the boot path is testable). */
export function adoptRenderingInfo(info: RenderingInfoLike | null | undefined): void {
  if (!info || typeof info !== 'object') {
    return
  }

  $softwareRendering.set(info.software === true)
  $softwareRenderingReason.set(typeof info.reason === 'string' && info.reason ? info.reason : null)
}

if (typeof window !== 'undefined') {
  $visualEffectsPreference.subscribe(preference => persistString(PREFERENCE_KEY, preference))
  $softwareRendering.subscribe(software => persistBoolean(SOFTWARE_RENDERING_KEY, software))
  $visualEffects.subscribe(level => applyVisualEffects(level, document.documentElement))

  // The machine fact, fresh for this launch. Missing bridge (web preview, an
  // older preload) keeps the remembered answer; a failed call too.
  void window.roboDesktop
    ?.getRenderingInfo?.()
    .then(info => adoptRenderingInfo(info))
    .catch(() => undefined)
}
