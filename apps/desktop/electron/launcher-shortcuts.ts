/**
 * launcher-shortcuts.ts
 *
 * Gives a desktop app that `robo desktop` built in place a launcher presence,
 * so people can start Robo the way they start every other app:
 *
 * - Windows: a Start menu entry, plus a desktop shortcut the first time. The
 *   full installer (install.ps1) writes the same pair; `robo desktop` runs
 *   the unpacked build straight from the checkout, which had neither.
 * - Linux: a desktop icon, copied from the app-menu entry `robo desktop`
 *   already writes (robo_cli/linux_desktop_entry.py), once.
 * - macOS: "Robo" in ~/Applications (Launchpad, Spotlight, Finder) — a small
 *   launcher app that opens the real Robo.app where it was built.
 *
 * Rules every platform follows:
 * - Best-effort: a failure is logged and costs only the shortcut, never the
 *   launch.
 * - Never take over a launcher that belongs to another install of Robo, and
 *   never overwrite something we did not write.
 * - The desktop icon is offered once. Deleting it is a choice, not a reason to
 *   put it back on the next start.
 * - Only the unpacked build that `robo desktop` / the installer scripts make
 *   (`release/<platform>-unpacked`, `release/mac-…/Robo.app`) is handled. An app
 *   installed by its own installer (NSIS, DMG, AppImage, deb/rpm) owns its
 *   launchers, and source/dev runs (the stock Electron binary) are left alone —
 *   on Windows windows-app-identity.ts already handles those.
 *
 * Dependency-free (no `electron` import) so the planning is unit-testable;
 * main.ts injects the Electron and filesystem calls.
 */

import path from 'node:path'

import { isElectronBinary, ROBO_APP_USER_MODEL_ID, type WindowsShortcutOptions } from './windows-app-identity'

export const LAUNCHER_NAME = 'Robo'

/** electron-builder's unpacked output (`release/win-unpacked`,
 *  `release/linux-arm64-unpacked`, …): the build `robo desktop` runs. */
const UNPACKED_BUILD = {
  linux: /[\\/]release[\\/]linux(?:-[a-z0-9]+)?-unpacked[\\/][^\\/]+$/i,
  win: /[\\/]release[\\/]win(?:-[a-z0-9]+)?-unpacked[\\/][^\\/]+$/i
}

export function isUnpackedBuild(execPath: string, platform: keyof typeof UNPACKED_BUILD): boolean {
  return UNPACKED_BUILD[platform].test(execPath)
}

// ─── Windows ────────────────────────────────────────────────────────────────

export interface WindowsLauncherInput {
  /** `app.getPath('desktop')`, or null when unknown. */
  desktopDir: null | string
  /** Running executable (the packaged Robo.exe). */
  execPath: string
  /** Does a file exist at this path? */
  fileExists: (filePath: string) => boolean
  /** resources\icon.ico when present; the exe's own icon otherwise. */
  iconPath: null | string | undefined
  packaged: boolean
  /** `%APPDATA%\Microsoft\Windows\Start Menu\Programs`, or null. */
  programsDir: null | string
  /** Target of the shortcut at this path, or null when there is none. */
  readShortcutTarget: (linkPath: string) => null | string
}

export interface PlannedWindowsShortcut {
  operation: 'create' | 'replace'
  options: WindowsShortcutOptions
  path: string
}

const winJoin = (dir: string, name: string) => (dir.endsWith('\\') ? `${dir}${name}` : `${dir}\\${name}`)

const sameWindowsPath = (a: null | string | undefined, b: string) =>
  Boolean(a) && String(a).replace(/\//g, '\\').toLowerCase() === b.replace(/\//g, '\\').toLowerCase()

/**
 * Which shortcuts to write. The Start menu entry is kept present; the desktop
 * shortcut is written only alongside a Start menu entry we create, i.e. when
 * no installer (and no earlier run) has given Robo a launcher yet — so a
 * deliberately deleted desktop shortcut stays deleted.
 */
export function planWindowsLaunchers(input: WindowsLauncherInput): PlannedWindowsShortcut[] {
  if (
    !input.packaged ||
    isElectronBinary(input.execPath) ||
    !isUnpackedBuild(input.execPath, 'win') ||
    !input.programsDir
  ) {
    return []
  }

  const options: WindowsShortcutOptions = {
    appUserModelId: ROBO_APP_USER_MODEL_ID,
    args: '',
    cwd: path.win32.dirname(input.execPath),
    description: LAUNCHER_NAME,
    icon: input.iconPath || input.execPath,
    iconIndex: 0,
    target: input.execPath
  }

  const startMenuPath = winJoin(input.programsDir, `${LAUNCHER_NAME}.lnk`)
  const startMenu = slotPlan(input, startMenuPath)

  if (!startMenu) {
    return []
  }

  const plans: PlannedWindowsShortcut[] = [{ operation: startMenu, options, path: startMenuPath }]

  if (startMenu === 'create' && input.desktopDir) {
    const desktopPath = winJoin(input.desktopDir, `${LAUNCHER_NAME}.lnk`)

    if (!input.fileExists(desktopPath)) {
      plans.push({ operation: 'create', options, path: desktopPath })
    }
  }

  return plans
}

/** create = nothing there; replace = a dead shortcut (its exe is gone); null =
 *  leave it (already ours, or another live install of Robo owns the name). */
function slotPlan(input: WindowsLauncherInput, linkPath: string): 'create' | 'replace' | null {
  if (!input.fileExists(linkPath)) {
    return 'create'
  }

  const target = input.readShortcutTarget(linkPath)

  if (!target || sameWindowsPath(target, input.execPath) || input.fileExists(target)) {
    return null
  }

  return 'replace'
}

// ─── Linux ──────────────────────────────────────────────────────────────────

export const LINUX_ENTRY_FILE = 'robo.desktop'

export interface LinuxLauncherInput {
  /** `app.getPath('desktop')` (the XDG desktop folder), or null. */
  desktopDir: null | string
  /** Whether that folder exists. We never create ~/Desktop. */
  desktopDirExists: boolean
  /** Whether a robo.desktop already sits in that folder. */
  desktopEntryExists: boolean
  /** Contents of the app-menu entry `robo desktop` wrote, or null. */
  menuEntry: null | string
  /** The desktop icon was offered before (see LauncherState). */
  offered: boolean
}

export interface PlannedLinuxDesktopIcon {
  contents: string
  path: string
}

/** A desktop icon that launches exactly what the app-menu entry launches
 *  (`robo desktop`, which also keeps the build current). Null = nothing to do. */
export function planLinuxDesktopIcon(input: LinuxLauncherInput): null | PlannedLinuxDesktopIcon {
  if (input.offered || !input.desktopDir || !input.desktopDirExists || input.desktopEntryExists) {
    return null
  }

  const contents = input.menuEntry ?? ''

  if (!/^\[Desktop Entry\]/m.test(contents) || !/^Exec=\S/m.test(contents)) {
    return null
  }

  return { contents, path: path.posix.join(input.desktopDir, LINUX_ENTRY_FILE) }
}

/** `$XDG_DATA_HOME/applications/robo.desktop` — the entry robo_cli writes. */
export function linuxMenuEntryPath(env: Record<string, string | undefined>, homeDir: string): string {
  const dataHome = env.XDG_DATA_HOME?.trim() || path.posix.join(homeDir, '.local', 'share')

  return path.posix.join(dataHome, 'applications', LINUX_ENTRY_FILE)
}

// ─── macOS ──────────────────────────────────────────────────────────────────

/** Marker inside our launcher app: it names the Robo.app it opens. Its
 *  presence is also how we know a ~/Applications/Robo.app is ours to manage. */
export const MAC_LAUNCHER_MARKER = path.posix.join('Contents', 'Resources', 'robo-launcher-target.txt')

/** `/…/Robo.app/Contents/MacOS/Robo` → `/…/Robo.app`, else null. */
export function macAppBundleOf(execPath: string): null | string {
  const match = /^(.*\.app)\/Contents\/MacOS\/[^/]+$/.exec(execPath)

  return match ? match[1] : null
}

/** `…/release/mac/Robo.app`, `…/release/mac-arm64/Robo.app`: the bundle
 *  `robo desktop` builds in place. Never a DMG volume, a translocated copy or
 *  a download folder — a launcher pointing there would break. */
export function isMacReleaseBundle(bundlePath: string): boolean {
  return /\/release\/mac(?:-[a-z0-9]+)?\/[^/]+\.app$/i.test(bundlePath)
}

export interface MacLauncherInput {
  execPath: string
  /** Does something exist at this path? */
  exists: (filePath: string) => boolean
  homeDir: string
  packaged: boolean
  /** Contents of MAC_LAUNCHER_MARKER inside this bundle, or null. */
  readMarker: (bundlePath: string) => null | string
}

export interface PlannedMacLauncher {
  /** The launcher app to (re)create. */
  launcherPath: string
  /** Whether an older launcher of ours must be removed first. */
  replace: boolean
  /** The real app the launcher opens. */
  targetBundle: string
}

export function planMacLauncher(input: MacLauncherInput): null | PlannedMacLauncher {
  const bundle = macAppBundleOf(input.execPath)

  if (!input.packaged || !bundle || isElectronBinary(input.execPath) || !isMacReleaseBundle(bundle)) {
    return null
  }

  const userApplications = path.posix.join(input.homeDir, 'Applications')
  const inside = (dir: string) => bundle.startsWith(`${dir}/`)

  // Already an installed app (DMG / drag-to-Applications): it is the launcher.
  if (inside('/Applications') || inside(userApplications)) {
    return null
  }

  // Another Robo is installed system-wide; don't add a second "Robo".
  if (input.exists(`/Applications/${LAUNCHER_NAME}.app`)) {
    return null
  }

  const launcherPath = path.posix.join(userApplications, `${LAUNCHER_NAME}.app`)

  if (!input.exists(launcherPath)) {
    return { launcherPath, replace: false, targetBundle: bundle }
  }

  const marker = input.readMarker(launcherPath)

  // Not ours (a real installed app) — or ours and already pointing here.
  if (marker === null || marker.trim() === bundle) {
    return null
  }

  return { launcherPath, replace: true, targetBundle: bundle }
}

/** A double-quoted AppleScript string literal for `value`. */
export function appleScriptString(value: string): string {
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}

/** The launcher's whole program: open the real app (or focus it if running). */
export function macLauncherScript(targetBundle: string): string {
  return `do shell script "/usr/bin/open " & quoted form of ${appleScriptString(targetBundle)}`
}

// ─── Persisted state ────────────────────────────────────────────────────────

/** `launcher-shortcuts.json` in userData: what was offered once already. */
export interface LauncherState {
  linuxDesktopIconOffered?: boolean
  /** The Robo.app a macOS launcher last failed to build for; not retried on
   *  every start (only once the app lives somewhere else). */
  macLauncherFailedFor?: string
}

export function parseLauncherState(raw: null | string | undefined): LauncherState {
  try {
    const value = JSON.parse(String(raw ?? ''))

    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return {}
    }

    const state: LauncherState = { linuxDesktopIconOffered: value.linuxDesktopIconOffered === true }

    if (typeof value.macLauncherFailedFor === 'string' && value.macLauncherFailedFor) {
      state.macLauncherFailedFor = value.macLauncherFailedFor
    }

    return state
  } catch {
    return {}
  }
}
