/**
 * windows-app-identity.ts
 *
 * How the desktop identifies itself to Windows, and how it gets Robo's icon
 * onto the taskbar and into the Start menu. Dependency-free so it can be
 * unit-tested without Electron; main.ts applies the plan.
 *
 * Windows groups taskbar buttons by AppUserModelID and takes the button's
 * icon from the Start Menu shortcut that carries the same id. A shortcut is
 * also what makes toast notifications work for a Win32 app.
 *
 * - Packaged app: the installer registers a shortcut whose id is the build
 *   `appId` (com.igniteenow.robo). Running under that id makes toasts work
 *   and the taskbar shows the shortcut's icon.
 * - From source (`robo desktop --source`, `npm run dev`): there is no such
 *   shortcut. Under the packaged id Windows fell back to the icon of the
 *   process executable — electron.exe's atom. The from-source app therefore
 *   runs under its own id and writes its own Start Menu shortcut carrying
 *   Robo's icon (assets/icon.ico), pointing at the same electron.exe + app
 *   folder that launched it. The taskbar and the Start menu then both show
 *   the Robo mark, and toasts work from source too.
 *
 * "From source" is decided by the executable, not only by a packaged flag:
 * the production main bundle bakes ROBO_DESKTOP_IS_PACKAGED=true so that
 * `electron .` loads dist/ like a packaged app (bundle-electron-main.mjs),
 * and `robo desktop --source` runs exactly that bundle. A process whose
 * executable is electron.exe is a source run whatever the flag says — it has
 * no installer shortcut, so it needs its own.
 */

/** package.json `build.appId` — keep in sync. */
export const ROBO_APP_USER_MODEL_ID = 'com.igniteenow.robo'
export const ROBO_SOURCE_APP_USER_MODEL_ID = 'com.igniteenow.robo.source'

export interface WindowsShortcutOptions {
  appUserModelId: string
  args: string
  cwd: string
  description: string
  icon: string
  iconIndex: number
  target: string
}

export interface WindowsShortcutPlan {
  options: WindowsShortcutOptions
  path: string
}

export interface WindowsAppIdentity {
  appUserModelId: string
  /** Null when nothing needs writing (packaged, or no icon / Start menu). */
  shortcut: null | WindowsShortcutPlan
}

export interface WindowsAppIdentityInput {
  /** Electron's app path (the folder with package.json). */
  appPath: string
  execPath: string
  /** Where an existing `Robo.lnk` in the Start menu points, if there is one. */
  existingRoboShortcutTarget?: null | string
  iconPath: null | string | undefined
  packaged: boolean
  /** `%APPDATA%\Microsoft\Windows\Start Menu\Programs`, or null when unknown. */
  programsDir: null | string
}

const join = (dir: string, name: string) => (dir.endsWith('\\') ? `${dir}${name}` : `${dir}\\${name}`)

const sameFile = (a: null | string | undefined, b: string) =>
  Boolean(a) && String(a).replace(/\//g, '\\').toLowerCase() === b.replace(/\//g, '\\').toLowerCase()

/** The stock Electron binary (`electron.exe`, or `electron` on a dev box) —
 *  what `electron .`, `npm run dev` and `robo desktop --source` all run. */
export function isElectronBinary(execPath: string): boolean {
  const name = execPath.replace(/\//g, '\\').split('\\').at(-1)?.toLowerCase() ?? ''

  return name === 'electron.exe' || name === 'electron'
}

/** A from-source run: not packaged, or packaged in name only (the baked
 *  flag) while the executable is still electron.exe. */
export function runsFromSource(packaged: boolean, execPath: string): boolean {
  return !packaged || isElectronBinary(execPath)
}

export function planWindowsAppIdentity(input: WindowsAppIdentityInput): WindowsAppIdentity {
  if (!runsFromSource(input.packaged, input.execPath)) {
    return { appUserModelId: ROBO_APP_USER_MODEL_ID, shortcut: null }
  }

  if (!input.iconPath || !input.programsDir) {
    return { appUserModelId: ROBO_SOURCE_APP_USER_MODEL_ID, shortcut: null }
  }

  // "Robo" unless another app's shortcut already owns that name (an installed
  // packaged Robo); then "Robo (source)" beside it. Our own earlier shortcut
  // keeps the name it has.
  const existing = input.existingRoboShortcutTarget
  const ownsRoboName = !existing || sameFile(existing, input.execPath)

  return {
    appUserModelId: ROBO_SOURCE_APP_USER_MODEL_ID,
    shortcut: {
      options: {
        appUserModelId: ROBO_SOURCE_APP_USER_MODEL_ID,
        args: `"${input.appPath}"`,
        cwd: input.appPath,
        description: 'Robo Desktop (from source)',
        icon: input.iconPath,
        iconIndex: 0,
        target: input.execPath
      },
      path: join(input.programsDir, ownsRoboName ? 'Robo.lnk' : 'Robo (source).lnk')
    }
  }
}

/** Whether an existing shortcut already matches the plan (nothing to write). */
export function shortcutMatches(
  existing: null | Partial<WindowsShortcutOptions> | undefined,
  wanted: WindowsShortcutOptions
): boolean {
  if (!existing) {
    return false
  }

  return (
    sameFile(existing.target, wanted.target) &&
    sameFile(existing.icon, wanted.icon) &&
    (existing.args ?? '') === wanted.args &&
    (existing.appUserModelId ?? '') === wanted.appUserModelId
  )
}

export function windowsStartMenuProgramsDir(env: Record<string, string | undefined>): null | string {
  const appData = env.APPDATA?.trim()

  return appData ? join(appData, 'Microsoft\\Windows\\Start Menu\\Programs') : null
}

/** The id alone — what main.ts sets before any window exists; the shortcut
 *  (planWindowsAppIdentity) follows once the app is ready. */
export function windowsAppUserModelId(packaged: boolean, execPath: string): string {
  return runsFromSource(packaged, execPath) ? ROBO_SOURCE_APP_USER_MODEL_ID : ROBO_APP_USER_MODEL_ID
}
