/**
 * Which Robo install the desktop app updates, and the command it shows when
 * the user has to run the update themselves.
 *
 * Pure helpers (paths and file checks are injected) so they can be tested
 * without Electron.
 */

import path from 'node:path'

/**
 * Pids a handed-off `robo update` waits for before touching the install.
 * Keep in sync with UPDATE_HANDOFF_ENV in robo_cli/update_cmd.py.
 */
export const UPDATE_HANDOFF_PIDS_ENV = 'ROBO_UPDATE_HANDOFF_PIDS'

type IsSourceRoot = (dir: string) => boolean
type FileExists = (file: string) => boolean
type ReadText = (file: string) => string | null

const MAX_LEVELS = 12

function pathApi(isWindows: boolean) {
  return isWindows ? path.win32 : path.posix
}

function isInside(child: string, parent: string, isWindows: boolean): boolean {
  const p = pathApi(isWindows)
  const relative = p.relative(parent, child)

  return Boolean(relative) && !relative.startsWith('..') && !p.isAbsolute(relative)
}

/**
 * The checkout a packaged app was built in, or null.
 *
 * `robo desktop` builds the app into `<checkout>/apps/desktop/release/` and
 * runs it from there, so that checkout is the install this app belongs to:
 * the one to check for updates and to update. An app installed anywhere else
 * (Program Files, /Applications, a copied folder) returns null and keeps
 * using the shared install.
 */
export function checkoutRootForExecutable(
  execPath: string,
  isSourceRoot: IsSourceRoot,
  isWindows = process.platform === 'win32'
): string | null {
  const p = pathApi(isWindows)
  const exe = p.resolve(execPath)
  let dir = p.dirname(exe)

  for (let level = 0; level < MAX_LEVELS; level++) {
    if (isInside(exe, p.join(dir, 'apps', 'desktop', 'release'), isWindows) && isSourceRoot(dir)) {
      return dir
    }

    const parent = p.dirname(dir)

    if (parent === dir) {
      break
    }

    dir = parent
  }

  return null
}

/** True when two paths name the same directory (case-insensitive on Windows). */
export function isSamePath(a: string, b: string, isWindows = process.platform === 'win32'): boolean {
  const p = pathApi(isWindows)
  const left = p.resolve(a)
  const right = p.resolve(b)

  return isWindows ? left.toLowerCase() === right.toLowerCase() : left === right
}

/**
 * The virtualenv a checkout runs from, picked the way `robo update` picks it
 * (`managed_uv.project_venv_dir`): `venv` when it has an interpreter, else
 * `.venv` (what install-robo.sh / install-robo.ps1 create). Null when neither
 * has one.
 */
export function venvDirForRoot(
  root: string,
  fileExists: FileExists,
  isWindows = process.platform === 'win32'
): string | null {
  const p = pathApi(isWindows)

  for (const name of ['venv', '.venv']) {
    const python = isWindows ? p.join(root, name, 'Scripts', 'python.exe') : p.join(root, name, 'bin', 'python')

    if (fileExists(python)) {
      return p.join(root, name)
    }
  }

  return null
}

/** The checkout's own `robo.exe`, so a pasted command can't reach another install. */
export function windowsLauncherForRoot(root: string, fileExists: FileExists): string | null {
  const venv = venvDirForRoot(root, fileExists, true)
  const launcher = venv ? path.win32.join(venv, 'Scripts', 'robo.exe') : null

  return launcher && fileExists(launcher) ? launcher : null
}

/**
 * Arguments for the checkout's venv python when "Update now" can't show the
 * update window: `robo update` opens its own console window (the app has
 * none), waits for the app to quit, and reopens it when it succeeds.
 */
export function windowsUpdateInWindowArgs(branch: string | null, reopen: 'packaged' | 'source'): string[] {
  const branchArgs = branch && branch !== 'main' ? ['--branch', branch] : []

  return ['-m', 'robo_cli.main', 'update', '--yes', ...branchArgs, '--new-window', '--reopen-desktop', reopen]
}

/** The updater window's script inside a checkout (robo_cli/update_window.py). */
export function windowsUpdateWindowScript(root: string): string {
  return path.win32.join(root, 'robo_cli', 'update_window.py')
}

/**
 * The windowed interpreter that shows the update window: the venv's base
 * Python (`home` in pyvenv.cfg), so the window holds no file inside the venv
 * the update may rebuild and Tk finds its library next to it. Falls back to
 * the venv's own pythonw.exe; null when there is neither.
 */
export function windowsUpdateWindowPython(venv: string, readText: ReadText, fileExists: FileExists): string | null {
  const p = path.win32
  const home = readText(p.join(venv, 'pyvenv.cfg'))?.match(/^\s*home\s*=\s*(.+?)\s*$/im)?.[1]

  const candidates = [
    home ? p.join(p.resolve(venv, home), 'pythonw.exe') : null,
    p.join(venv, 'Scripts', 'pythonw.exe')
  ]

  return candidates.find((candidate): candidate is string => Boolean(candidate && fileExists(candidate))) ?? null
}

export interface UpdateWindowLaunch {
  branch: string | null
  /** The venv interpreter the window runs `robo update` with. */
  python: string
  reopen: 'packaged' | 'source'
  root: string
  script: string
  /** This app's pid: the update starts once it has exited. */
  waitPid: number
}

/**
 * Arguments for the update window. `-I -S` keep it to the standard library:
 * no venv, no PYTHON* variables, nothing from the checkout on sys.path.
 */
export function windowsUpdateWindowArgs(launch: UpdateWindowLaunch): string[] {
  const branchArgs = launch.branch && launch.branch !== 'main' ? ['--branch', launch.branch] : []

  return [
    '-I',
    '-S',
    launch.script,
    '--python',
    launch.python,
    '--root',
    launch.root,
    '--reopen',
    launch.reopen,
    ...branchArgs,
    '--wait-pid',
    String(launch.waitPid)
  ]
}

// A path PowerShell and cmd.exe both run as-is when pasted.
const PLAIN_WINDOWS_PATH = /^[A-Za-z]:\\[A-Za-z0-9_.\\-]+$/

/**
 * The update command for the manual card on Windows.
 *
 * It names the checkout's own launcher when there is one: a bare `robo` runs
 * whichever install is first on PATH, which may not be this one. A path with
 * spaces needs PowerShell's call operator, the terminal Windows opens by
 * default.
 */
export function windowsManualUpdateCommand(launcher: string | null, branch?: string | null): string {
  const args = branch && branch !== 'main' ? ` update --branch ${branch}` : ' update'

  if (!launcher) {
    return `robo${args}`
  }

  if (PLAIN_WINDOWS_PATH.test(launcher)) {
    return `${launcher}${args}`
  }

  return `& '${launcher.replace(/'/g, "''")}'${args}`
}
