// `robo desktop` runs Robo from its build folder, so the app gives itself a
// launcher presence: Start menu (+ desktop once) on Windows, a desktop icon on
// Linux, ~/Applications on macOS — without ever taking over a launcher that
// belongs to another install, or resurrecting one the user deleted.

import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  appleScriptString,
  isMacReleaseBundle,
  isUnpackedBuild,
  linuxMenuEntryPath,
  macAppBundleOf,
  macLauncherScript,
  parseLauncherState,
  planLinuxDesktopIcon,
  planMacLauncher,
  planWindowsLaunchers,
  type WindowsLauncherInput
} from './launcher-shortcuts'
import { ROBO_APP_USER_MODEL_ID } from './windows-app-identity'

// ─── Windows ────────────────────────────────────────────────────────────────

const EXE = 'C:\\Users\\alice\\Projects\\robo-local\\apps\\desktop\\release\\win-unpacked\\Robo.exe'
const ICO = 'C:\\Users\\alice\\Projects\\robo-local\\apps\\desktop\\release\\win-unpacked\\resources\\icon.ico'
const PROGRAMS = 'C:\\Users\\alice\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs'
const DESKTOP = 'C:\\Users\\alice\\Desktop'
const START_LNK = `${PROGRAMS}\\Robo.lnk`
const DESKTOP_LNK = `${DESKTOP}\\Robo.lnk`

function windows(files: Record<string, null | string> = {}, over: Partial<WindowsLauncherInput> = {}) {
  // `files`: path → shortcut target (null for a plain file / unreadable link).
  const exists = new Set([EXE, ICO, ...Object.keys(files)])

  return planWindowsLaunchers({
    desktopDir: DESKTOP,
    execPath: EXE,
    fileExists: filePath => exists.has(filePath),
    iconPath: ICO,
    packaged: true,
    programsDir: PROGRAMS,
    readShortcutTarget: linkPath => files[linkPath] ?? null,
    ...over
  })
}

test('windows: no launcher yet → Start menu entry and desktop shortcut, both opening this Robo.exe', () => {
  const plans = windows()

  assert.deepEqual(
    plans.map(plan => [plan.path, plan.operation]),
    [
      [START_LNK, 'create'],
      [DESKTOP_LNK, 'create']
    ]
  )

  for (const plan of plans) {
    assert.equal(plan.options.target, EXE)
    assert.equal(plan.options.cwd, 'C:\\Users\\alice\\Projects\\robo-local\\apps\\desktop\\release\\win-unpacked')
    assert.equal(plan.options.icon, ICO)
    assert.equal(plan.options.args, '')
    // Same id the packaged app runs under: taskbar grouping + toasts.
    assert.equal(plan.options.appUserModelId, ROBO_APP_USER_MODEL_ID)
  }
})

test('windows: our Start menu entry already there → nothing, and a deleted desktop shortcut stays deleted', () => {
  assert.deepEqual(windows({ [START_LNK]: EXE }), [])
})

test('windows: same exe, different spelling of the path → still ours', () => {
  assert.deepEqual(windows({ [START_LNK]: EXE.toUpperCase().replace(/\\/g, '/') }), [])
})

test('windows: another live Robo install owns the Start menu entry → leave it (and the desktop) alone', () => {
  const installed = 'C:\\Users\\alice\\AppData\\Local\\Programs\\Robo\\Robo.exe'

  assert.deepEqual(windows({ [installed]: null, [START_LNK]: installed }), [])
})

test('windows: a dead Start menu entry (its exe is gone) is repointed here, desktop untouched', () => {
  const plans = windows({ [START_LNK]: 'D:\\old\\Robo.exe' })

  assert.deepEqual(
    plans.map(plan => [plan.path, plan.operation]),
    [[START_LNK, 'replace']]
  )
})

test('windows: an unreadable Start menu entry is never overwritten', () => {
  assert.deepEqual(windows({ [START_LNK]: null }), [])
})

test('windows: a desktop file already named Robo.lnk is not overwritten', () => {
  const plans = windows({ [DESKTOP_LNK]: 'D:\\something-else.exe' })

  assert.deepEqual(
    plans.map(plan => plan.path),
    [START_LNK]
  )
})

test('windows: no desktop folder → Start menu only', () => {
  assert.deepEqual(
    windows({}, { desktopDir: null }).map(plan => plan.path),
    [START_LNK]
  )
})

test('windows: source runs, unpackaged runs and an unknown Start menu are left alone', () => {
  assert.deepEqual(windows({}, { execPath: 'C:\\robo\\node_modules\\electron\\dist\\electron.exe' }), [])
  assert.deepEqual(windows({}, { packaged: false }), [])
  assert.deepEqual(windows({}, { programsDir: null }), [])
})

test('windows: an installer-installed Robo owns its launchers (incl. all-users installs) → nothing', () => {
  assert.deepEqual(windows({}, { execPath: 'C:\\Users\\alice\\AppData\\Local\\Programs\\Robo\\Robo.exe' }), [])
  assert.deepEqual(windows({}, { execPath: 'C:\\Program Files\\Robo\\Robo.exe' }), [])
})

test('unpacked builds are recognised on every arch, and nothing else is', () => {
  assert.equal(isUnpackedBuild(EXE, 'win'), true)
  assert.equal(isUnpackedBuild('D:\\robo\\apps\\desktop\\release\\win-arm64-unpacked\\Robo.exe', 'win'), true)
  assert.equal(
    isUnpackedBuild('/home/alice/.robo/robo-engineer/apps/desktop/release/linux-unpacked/robo', 'linux'),
    true
  )
  assert.equal(
    isUnpackedBuild('/home/alice/.robo/robo-engineer/apps/desktop/release/linux-arm64-unpacked/Robo', 'linux'),
    true
  )
  assert.equal(isUnpackedBuild('/opt/Robo/robo', 'linux'), false)
  assert.equal(isUnpackedBuild('/tmp/.mount_RoboXYZ/robo', 'linux'), false)
  assert.equal(isUnpackedBuild(EXE, 'linux'), false)
})

test('windows: without the .ico the exe supplies its own icon', () => {
  assert.equal(windows({}, { iconPath: null })[0].options.icon, EXE)
})

// ─── Linux ──────────────────────────────────────────────────────────────────

const MENU_ENTRY = [
  '[Desktop Entry]',
  'Type=Application',
  'Name=Robo',
  'Exec=/home/alice/.local/bin/robo desktop',
  'Icon=/home/alice/.robo/robo-engineer/apps/desktop/assets/icon.png',
  'Terminal=false',
  ''
].join('\n')

const linux = (over = {}) =>
  planLinuxDesktopIcon({
    desktopDir: '/home/alice/Desktop',
    desktopDirExists: true,
    desktopEntryExists: false,
    menuEntry: MENU_ENTRY,
    offered: false,
    ...over
  })

test('linux: the desktop icon launches exactly what the app-menu entry launches', () => {
  assert.deepEqual(linux(), { contents: MENU_ENTRY, path: '/home/alice/Desktop/robo.desktop' })
})

test('linux: offered once — a deleted desktop icon is not put back', () => {
  assert.equal(linux({ offered: true }), null)
})

test('linux: never overwrites, never creates ~/Desktop, never invents an entry', () => {
  assert.equal(linux({ desktopEntryExists: true }), null)
  assert.equal(linux({ desktopDirExists: false }), null)
  assert.equal(linux({ desktopDir: null }), null)
  assert.equal(linux({ menuEntry: null }), null)
  assert.equal(linux({ menuEntry: 'garbage' }), null)
  assert.equal(linux({ menuEntry: '[Desktop Entry]\nName=Robo\n' }), null)
})

test('linux: the app-menu entry path follows XDG_DATA_HOME, like robo_cli', () => {
  assert.equal(linuxMenuEntryPath({}, '/home/alice'), '/home/alice/.local/share/applications/robo.desktop')
  assert.equal(linuxMenuEntryPath({ XDG_DATA_HOME: '/data' }, '/home/alice'), '/data/applications/robo.desktop')
  assert.equal(
    linuxMenuEntryPath({ XDG_DATA_HOME: '  ' }, '/home/alice'),
    '/home/alice/.local/share/applications/robo.desktop'
  )
})

// ─── macOS ──────────────────────────────────────────────────────────────────

const MAC_APP = '/Users/alice/.robo/robo-engineer/apps/desktop/release/mac-arm64/Robo.app'
const MAC_EXE = `${MAC_APP}/Contents/MacOS/Robo`
const LAUNCHER = '/Users/alice/Applications/Robo.app'

function mac(existing: Record<string, null | string> = {}, over = {}) {
  // `existing`: path → launcher marker contents (null = exists, not ours).
  return planMacLauncher({
    execPath: MAC_EXE,
    exists: filePath => filePath in existing,
    homeDir: '/Users/alice',
    packaged: true,
    readMarker: bundlePath => existing[bundlePath] ?? null,
    ...over
  })
}

test('mac: the built app gets a launcher in ~/Applications pointing at it', () => {
  assert.deepEqual(mac(), { launcherPath: LAUNCHER, replace: false, targetBundle: MAC_APP })
})

test('mac: our launcher already points here → nothing; points elsewhere → rebuilt', () => {
  assert.equal(mac({ [LAUNCHER]: `${MAC_APP}\n` }), null)
  assert.deepEqual(mac({ [LAUNCHER]: '/old/place/Robo.app' }), {
    launcherPath: LAUNCHER,
    replace: true,
    targetBundle: MAC_APP
  })
})

test('mac: a real Robo.app in either Applications folder is never touched or duplicated', () => {
  assert.equal(mac({ [LAUNCHER]: null }), null)
  assert.equal(mac({ '/Applications/Robo.app': null }), null)
})

test('mac: an installed app is its own launcher; source runs are left alone', () => {
  assert.equal(mac({}, { execPath: '/Applications/Robo.app/Contents/MacOS/Robo' }), null)
  assert.equal(mac({}, { execPath: `${LAUNCHER}/Contents/MacOS/Robo` }), null)
  assert.equal(mac({}, { execPath: '/x/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron' }), null)
  assert.equal(mac({}, { packaged: false }), null)
  assert.equal(mac({}, { execPath: '/usr/local/bin/robo' }), null)
})

test('mac: a DMG volume, a translocated copy or a download folder never gets a launcher', () => {
  assert.equal(mac({}, { execPath: '/Volumes/Robo 3.0.1/Robo.app/Contents/MacOS/Robo' }), null)
  assert.equal(
    mac({}, { execPath: '/private/var/folders/x/AppTranslocation/1234/d/Robo.app/Contents/MacOS/Robo' }),
    null
  )
  assert.equal(mac({}, { execPath: '/Users/alice/Downloads/Robo.app/Contents/MacOS/Robo' }), null)
  assert.equal(isMacReleaseBundle(MAC_APP), true)
  assert.equal(isMacReleaseBundle('/Users/alice/robo/apps/desktop/release/mac/Robo.app'), true)
})

test('mac: bundle and AppleScript helpers', () => {
  assert.equal(macAppBundleOf(MAC_EXE), MAC_APP)
  assert.equal(macAppBundleOf('/usr/bin/robo'), null)
  assert.equal(appleScriptString('/a "b"\\c'), '"/a \\"b\\"\\\\c"')
  assert.equal(macLauncherScript(MAC_APP), `do shell script "/usr/bin/open " & quoted form of "${MAC_APP}"`)
})

// ─── State ──────────────────────────────────────────────────────────────────

test('state: only a literal true counts as offered; anything malformed reads as fresh', () => {
  assert.deepEqual(parseLauncherState('{"linuxDesktopIconOffered":true}'), { linuxDesktopIconOffered: true })
  assert.deepEqual(parseLauncherState('{"macLauncherFailedFor":"/x/Robo.app"}'), {
    linuxDesktopIconOffered: false,
    macLauncherFailedFor: '/x/Robo.app'
  })
  assert.deepEqual(parseLauncherState('{"macLauncherFailedFor":""}'), { linuxDesktopIconOffered: false })
  assert.deepEqual(parseLauncherState('{"linuxDesktopIconOffered":"yes"}'), { linuxDesktopIconOffered: false })
  assert.deepEqual(parseLauncherState('[]'), {})
  assert.deepEqual(parseLauncherState('not json'), {})
  assert.deepEqual(parseLauncherState(null), {})
})
