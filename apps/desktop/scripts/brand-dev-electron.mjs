#!/usr/bin/env node
// brand-dev-electron.mjs — give the Electron binary a from-source run uses
// (node_modules/electron/dist/electron.exe) Robo's icon and identity, the
// same way after-pack.mjs brands the packed Robo.exe.
//
// WHY THIS EXISTS
// ---------------
// On Windows the taskbar button, the Alt-Tab tile and the Start menu's
// "recently added" row all come from the EXECUTABLE's icon resource. A
// packed Robo.exe gets Robo's icon stamped in by rcedit (set-exe-identity.mjs,
// from the afterPack hook). `robo desktop --source` and `npm run dev` never
// pack: they run the stock electron.exe, whose icon is the Electron atom.
// Setting the window icon and an app id with its own Start Menu shortcut
// (main.ts) covers what those APIs cover; the executable's own icon is what
// Windows falls back to everywhere else, and it was still the atom.
//
// So the source build stamps electron.exe itself. rcedit only rewrites PE
// resources (icon + version strings); the binary runs exactly as before.
// `npm ci` re-extracts a stock electron.exe, and this step runs from the
// `build` script, so every source build re-brands it.
//
// Best-effort by design: a running Robo holds electron.exe open (Windows
// refuses the rewrite), rcedit may be missing in a trimmed install — either
// way the build must still succeed, with the stock icon and a clear line in
// the output saying why.

import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'

import { isMain } from './utils.mjs'

/** Windows only, unless explicitly skipped (CI images, read-only trees). */
export function shouldBrandDevElectron(platform = process.platform, env = process.env) {
  const skip = String(env.ROBO_DESKTOP_SKIP_EXE_BRAND || '')
    .trim()
    .toLowerCase()

  return platform === 'win32' && !['1', 'true', 'yes'].includes(skip)
}

/** The electron binary the `electron` package would launch, or null. */
export function resolveDevElectronBinary(require = createRequire(import.meta.url)) {
  try {
    const binary = require('electron')

    return typeof binary === 'string' && existsSync(binary) ? binary : null
  } catch {
    return null
  }
}

/** Why a stamp failed, in one line a person can act on. */
export function describeBrandFailure(error) {
  const message = error instanceof Error ? error.message : String(error)

  if (/EBUSY|being used by another process|Access is denied|EPERM/i.test(message)) {
    return 'electron.exe is in use — close the running Robo window and build again'
  }

  return message
}

export async function brandDevElectron({
  desktopRoot = resolve(import.meta.dirname, '..'),
  log = console,
  platform = process.platform,
  env = process.env
} = {}) {
  if (!shouldBrandDevElectron(platform, env)) {
    return { skipped: 'not windows' }
  }

  const binary = resolveDevElectronBinary()

  if (!binary) {
    log.warn('[brand-dev-electron] no electron binary under node_modules; nothing to brand')

    return { skipped: 'no binary' }
  }

  try {
    // Loaded here, not at the top: a tree without rcedit must still build.
    const { stampExeIdentity } = await import('./set-exe-identity.mjs')

    await stampExeIdentity(binary, desktopRoot)

    return { branded: binary }
  } catch (error) {
    const why = describeBrandFailure(error)
    log.warn(`[brand-dev-electron] could not brand ${binary}: ${why} (the taskbar keeps the Electron icon)`)

    return { failed: why }
  }
}

if (isMain(import.meta.url)) {
  brandDevElectron().catch(err => {
    console.warn(`[brand-dev-electron] ${err instanceof Error ? err.message : String(err)}`)
  })
}
