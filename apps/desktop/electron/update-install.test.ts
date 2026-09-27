/**
 * Tests for electron/update-install.ts — which install the desktop app
 * updates, and the command it shows when the user runs the update.
 *
 * Run with: npx vitest run --project electron electron/update-install.test.ts
 *
 * Why this matters: an app built by `robo desktop` checked for updates in
 * ~/.robo/robo-engineer instead of the checkout it was built from. Users who
 * installed from a clone never saw the update popup, and a user with an old
 * second install had that one checked and updated instead.
 */

import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  checkoutRootForExecutable,
  isSamePath,
  venvDirForRoot,
  windowsLauncherForRoot,
  windowsManualUpdateCommand,
  windowsUpdateInWindowArgs,
  windowsUpdateWindowArgs,
  windowsUpdateWindowPython,
  windowsUpdateWindowScript
} from './update-install'

const roots = (...dirs: string[]) => {
  const set = new Set(dirs)

  return (dir: string) => set.has(dir)
}

const anyDir = () => true
const noFile = () => false

test('a packaged Windows app finds the checkout that built it', () => {
  const checkout = 'C:\\Users\\me\\robo'
  const exe = `${checkout}\\apps\\desktop\\release\\win-unpacked\\Robo.exe`

  assert.equal(checkoutRootForExecutable(exe, roots(checkout), true), checkout)
})

test('a packaged macOS app finds the checkout that built it', () => {
  const checkout = '/Users/me/robo'
  const exe = `${checkout}/apps/desktop/release/mac-arm64/Robo.app/Contents/MacOS/Robo`

  assert.equal(checkoutRootForExecutable(exe, roots(checkout), false), checkout)
})

test('a packaged Linux app finds the checkout that built it', () => {
  const checkout = '/home/me/robo'
  const exe = `${checkout}/apps/desktop/release/linux-unpacked/robo`

  assert.equal(checkoutRootForExecutable(exe, roots(checkout), false), checkout)
})

test('an app installed outside a checkout keeps using the shared install', () => {
  const exe = 'C:\\Users\\me\\AppData\\Local\\Programs\\Robo\\Robo.exe'

  assert.equal(checkoutRootForExecutable(exe, anyDir, true), null)
  assert.equal(checkoutRootForExecutable('/Applications/Robo.app/Contents/MacOS/Robo', anyDir, false), null)
})

test('a folder above release/ that is not a Robo checkout is not claimed', () => {
  const exe = '/home/me/copies/apps/desktop/release/linux-unpacked/robo'

  assert.equal(checkoutRootForExecutable(exe, roots(), false), null)
})

test('a checkout is only claimed for apps inside its release folder', () => {
  // The app sits inside a checkout, but not in the folder `robo desktop` builds into.
  const checkout = '/home/me/robo'
  const exe = `${checkout}/tmp/Robo-portable/robo`

  assert.equal(checkoutRootForExecutable(exe, roots(checkout), false), null)
})

test('isSamePath ignores case and trailing separators on Windows only', () => {
  assert.equal(isSamePath('C:\\Users\\A\\.robo\\robo-engineer', 'c:\\users\\a\\.robo\\robo-engineer\\', true), true)
  assert.equal(isSamePath('C:\\Users\\A\\robo', 'C:\\Users\\A\\.robo\\robo-engineer', true), false)
  assert.equal(isSamePath('/home/a/Robo', '/home/a/robo', false), false)
  assert.equal(isSamePath('/home/a/robo/', '/home/a/robo', false), true)
})

test('the venv is picked like robo update picks it: venv, then .venv', () => {
  const root = 'C:\\robo'
  const both = roots(`${root}\\venv\\Scripts\\python.exe`, `${root}\\.venv\\Scripts\\python.exe`)
  const dotOnly = roots(`${root}\\.venv\\Scripts\\python.exe`)

  assert.equal(venvDirForRoot(root, both, true), `${root}\\venv`)
  assert.equal(venvDirForRoot(root, dotOnly, true), `${root}\\.venv`)
  assert.equal(venvDirForRoot(root, noFile, true), null)
  assert.equal(venvDirForRoot('/home/a/robo', roots('/home/a/robo/.venv/bin/python'), false), '/home/a/robo/.venv')
})

test('the launcher is the robo.exe of that same venv', () => {
  const root = 'C:\\robo'
  const dotVenv = roots(`${root}\\.venv\\Scripts\\python.exe`, `${root}\\.venv\\Scripts\\robo.exe`)
  const noLauncher = roots(`${root}\\.venv\\Scripts\\python.exe`)

  assert.equal(windowsLauncherForRoot(root, dotVenv), `${root}\\.venv\\Scripts\\robo.exe`)
  assert.equal(windowsLauncherForRoot(root, noLauncher), null)
  assert.equal(windowsLauncherForRoot(root, noFile), null)
})

test('Update now runs robo update in its own window and reopens the app', () => {
  assert.deepEqual(windowsUpdateInWindowArgs(null, 'packaged'), [
    '-m',
    'robo_cli.main',
    'update',
    '--yes',
    '--new-window',
    '--reopen-desktop',
    'packaged'
  ])
  assert.deepEqual(windowsUpdateInWindowArgs('main', 'source').slice(-2), ['--reopen-desktop', 'source'])
  assert.deepEqual(windowsUpdateInWindowArgs('bb/gui', 'packaged').slice(3, 6), ['--yes', '--branch', 'bb/gui'])
})

test('the update window runs on the venv’s base Python, windowed', () => {
  const venv = 'C:\\robo\\.venv'
  const home = 'C:\\Users\\me\\AppData\\Roaming\\uv\\python\\cpython-3.11.14-windows-x86_64-none'
  const cfg = (text: string | null) => (file: string) => (file === `${venv}\\pyvenv.cfg` ? text : null)
  const pyvenv = `home = ${home}\r\nimplementation = CPython\r\nversion_info = 3.11.14\r\n`

  assert.equal(windowsUpdateWindowPython(venv, cfg(pyvenv), roots(`${home}\\pythonw.exe`)), `${home}\\pythonw.exe`)
  // The base is gone or has no pythonw.exe: the venv's own one still works.
  assert.equal(
    windowsUpdateWindowPython(venv, cfg(pyvenv), roots(`${venv}\\Scripts\\pythonw.exe`)),
    `${venv}\\Scripts\\pythonw.exe`
  )
  assert.equal(
    windowsUpdateWindowPython(venv, cfg(null), roots(`${venv}\\Scripts\\pythonw.exe`)),
    `${venv}\\Scripts\\pythonw.exe`
  )
  assert.equal(windowsUpdateWindowPython(venv, cfg(pyvenv), noFile), null)
})

test('a relative home in pyvenv.cfg is read from the venv', () => {
  const venv = 'C:\\robo\\venv'
  const readText = () => 'home = ..\\runtime\\python\n'

  assert.equal(
    windowsUpdateWindowPython(venv, readText, roots('C:\\robo\\runtime\\python\\pythonw.exe')),
    'C:\\robo\\runtime\\python\\pythonw.exe'
  )
})

test('the update window gets the update it runs and the app it waits for', () => {
  const root = 'C:\\Users\\John Smith\\robo'
  const script = windowsUpdateWindowScript(root)

  const launch = {
    branch: null,
    python: `${root}\\venv\\Scripts\\python.exe`,
    reopen: 'packaged' as const,
    root,
    script,
    waitPid: 4242
  }

  assert.equal(script, `${root}\\robo_cli\\update_window.py`)
  assert.deepEqual(windowsUpdateWindowArgs(launch), [
    '-I',
    '-S',
    script,
    '--python',
    launch.python,
    '--root',
    root,
    '--reopen',
    'packaged',
    '--wait-pid',
    '4242'
  ])
  assert.deepEqual(windowsUpdateWindowArgs({ ...launch, branch: 'main' }), windowsUpdateWindowArgs(launch))
  assert.deepEqual(windowsUpdateWindowArgs({ ...launch, branch: 'bb/gui', reopen: 'source' }).slice(8, 12), [
    'source',
    '--branch',
    'bb/gui',
    '--wait-pid'
  ])
})

test('the manual command runs this checkout’s launcher, pasted as-is', () => {
  const launcher = 'C:\\Users\\me\\robo\\.venv\\Scripts\\robo.exe'

  assert.equal(windowsManualUpdateCommand(launcher), `${launcher} update`)
  assert.equal(windowsManualUpdateCommand(launcher, 'main'), `${launcher} update`)
  assert.equal(windowsManualUpdateCommand(launcher, 'bb/gui'), `${launcher} update --branch bb/gui`)
})

test('a launcher path with spaces or quotes uses PowerShell’s call operator', () => {
  assert.equal(
    windowsManualUpdateCommand('C:\\Users\\John Smith\\robo\\.venv\\Scripts\\robo.exe'),
    "& 'C:\\Users\\John Smith\\robo\\.venv\\Scripts\\robo.exe' update"
  )
  assert.equal(
    windowsManualUpdateCommand("C:\\Users\\O'Neil\\robo\\.venv\\Scripts\\robo.exe"),
    "& 'C:\\Users\\O''Neil\\robo\\.venv\\Scripts\\robo.exe' update"
  )
})

test('without a launcher the command falls back to robo on PATH', () => {
  assert.equal(windowsManualUpdateCommand(null), 'robo update')
  assert.equal(windowsManualUpdateCommand(null, 'dev'), 'robo update --branch dev')
})
