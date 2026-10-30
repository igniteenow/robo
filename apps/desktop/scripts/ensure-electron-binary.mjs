#!/usr/bin/env node
// ensure-electron-binary.mjs — download the Electron binary when the desktop
// workspace is installed (this workspace's `postinstall`).
//
// WHY THIS EXISTS
// ---------------
// Up to Electron 41 the `electron` package downloaded its binary from its own
// `postinstall` script, so after `npm ci` the binary was always at
// node_modules/electron/dist. Electron 42 dropped that script (supply-chain
// hardening: installs can run with --ignore-scripts) and downloads lazily the
// first time `electron` is launched. Everything here that expects the binary
// to be in place after an install would break:
//   - electron-builder's `electronDist` (scripts/run-electron-builder.mjs),
//   - `robo desktop`'s "toolchain ready" check and its electron-dist repair
//     (robo_cli/main.py), and the same checks in scripts/install.sh / .ps1,
//   - brand-dev-electron.mjs and the e2e runs.
// So this first-party script does what the old postinstall did, with the same
// code Electron ships for it (its `install.js`, the `install-electron` bin).
// It honours ELECTRON_MIRROR (read by @electron/get) like before, and fails
// the install the same way when the download fails, so the existing repair
// paths (fallback mirror, re-download) keep working unchanged.
//
// Skip with ELECTRON_SKIP_BINARY_DOWNLOAD=1 (the variable Electron itself
// honoured before 42) or ROBO_DESKTOP_SKIP_ELECTRON_DOWNLOAD=1.

import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'

import { isMain } from './utils.mjs'

const TRUTHY = new Set(['1', 'true', 'yes', 'on'])

export function shouldSkipElectronDownload(env = process.env) {
  return [env.ELECTRON_SKIP_BINARY_DOWNLOAD, env.ROBO_DESKTOP_SKIP_ELECTRON_DOWNLOAD].some(value =>
    TRUTHY.has(
      String(value || '')
        .trim()
        .toLowerCase()
    )
  )
}

/** The binary electron-builder and `robo desktop` look for (same rule as run-electron-builder.mjs). */
export function electronDistBinary(electronDir, platform = process.platform) {
  const dist = join(electronDir, 'dist')

  if (platform === 'darwin') {
    return join(dist, 'Electron.app', 'Contents', 'MacOS', 'Electron')
  }

  if (platform === 'win32') {
    return join(dist, 'electron.exe')
  }

  return join(dist, 'electron')
}

/** node_modules/electron, wherever npm hoisted it; null when it is not installed. */
export function resolveElectronDir(require = createRequire(import.meta.url)) {
  try {
    return dirname(require.resolve('electron/package.json'))
  } catch {
    return null
  }
}

export function ensureElectronBinary({
  env = process.env,
  log = console,
  platform = process.platform,
  electronDir = resolveElectronDir(),
  run = (installer, cwd) =>
    spawnSync(process.execPath, [installer], { cwd, env, stdio: 'inherit', windowsHide: true }).status
} = {}) {
  if (shouldSkipElectronDownload(env)) {
    log.log('[ensure-electron-binary] skipped (ELECTRON_SKIP_BINARY_DOWNLOAD / ROBO_DESKTOP_SKIP_ELECTRON_DOWNLOAD)')

    return { skipped: 'env' }
  }

  if (!electronDir) {
    // electron is a devDependency: a production-only install has no package
    // to download for, and that is not an error.
    return { skipped: 'not installed' }
  }

  if (existsSync(electronDistBinary(electronDir, platform))) {
    return { present: true }
  }

  const installer = join(electronDir, 'install.js')

  if (!existsSync(installer)) {
    log.warn(`[ensure-electron-binary] ${installer} is missing; cannot download the Electron binary`)

    return { failed: 'no installer', status: 1 }
  }

  log.log('[ensure-electron-binary] downloading the Electron binary (Electron 42+ no longer does this on install)')
  const status = run(installer, electronDir)

  if (status === 0 && existsSync(electronDistBinary(electronDir, platform))) {
    return { downloaded: true }
  }

  return { failed: 'download', status: typeof status === 'number' && status !== 0 ? status : 1 }
}

if (isMain(import.meta.url)) {
  const result = ensureElectronBinary()

  if (result.failed) {
    console.error(
      '[ensure-electron-binary] the Electron binary could not be downloaded. ' +
        'Set ELECTRON_MIRROR to a trusted mirror and install again, or run  npx install-electron --no  in apps/desktop.'
    )
    process.exit(result.status || 1)
  }
}
