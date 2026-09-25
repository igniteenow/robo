// Windows takes a taskbar button's icon from the Start Menu shortcut that
// carries the window's AppUserModelID. The packaged app has the installer's
// shortcut; a from-source run writes its own, with Robo's icon, so neither
// the taskbar nor the Start menu ever shows electron.exe's atom.

import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  isElectronBinary,
  planWindowsAppIdentity,
  ROBO_APP_USER_MODEL_ID,
  ROBO_SOURCE_APP_USER_MODEL_ID,
  runsFromSource,
  shortcutMatches,
  windowsAppUserModelId,
  windowsStartMenuProgramsDir
} from './windows-app-identity'

const EXE = 'C:\\robo\\apps\\desktop\\node_modules\\electron\\dist\\electron.exe'
const APP = 'C:\\robo\\apps\\desktop'
const ICON = 'C:\\robo\\apps\\desktop\\assets\\icon.ico'
const PROGRAMS = 'C:\\Users\\ahmad\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs'

test('packaged: the build appId and no shortcut of our own (the installer wrote it)', () => {
  const plan = planWindowsAppIdentity({
    appPath: 'C:\\Program Files\\Robo\\resources\\app.asar',
    execPath: 'C:\\Program Files\\Robo\\Robo.exe',
    iconPath: ICON,
    packaged: true,
    programsDir: PROGRAMS
  })

  assert.deepEqual(plan, { appUserModelId: ROBO_APP_USER_MODEL_ID, shortcut: null })
  assert.equal(ROBO_APP_USER_MODEL_ID, 'com.igniteenow.robo')
})

test('from source: its own id and a Start Menu shortcut carrying the Robo icon', () => {
  const plan = planWindowsAppIdentity({
    appPath: APP,
    execPath: EXE,
    iconPath: ICON,
    packaged: false,
    programsDir: PROGRAMS
  })

  assert.equal(plan.appUserModelId, ROBO_SOURCE_APP_USER_MODEL_ID)
  assert.notEqual(plan.appUserModelId, ROBO_APP_USER_MODEL_ID)
  assert.equal(plan.shortcut?.path, `${PROGRAMS}\\Robo.lnk`)
  assert.deepEqual(plan.shortcut?.options, {
    appUserModelId: ROBO_SOURCE_APP_USER_MODEL_ID,
    args: `"${APP}"`,
    cwd: APP,
    description: 'Robo Desktop (from source)',
    icon: ICON,
    iconIndex: 0,
    target: EXE
  })
})

test('from source: never steals an installed app’s "Robo" shortcut — sits beside it', () => {
  const plan = planWindowsAppIdentity({
    appPath: APP,
    execPath: EXE,
    existingRoboShortcutTarget: 'C:\\Program Files\\Robo\\Robo.exe',
    iconPath: ICON,
    packaged: false,
    programsDir: PROGRAMS
  })

  assert.equal(plan.shortcut?.path, `${PROGRAMS}\\Robo (source).lnk`)

  // Our own earlier shortcut (same electron.exe, case/slashes aside) keeps the name.
  const ours = planWindowsAppIdentity({
    appPath: APP,
    execPath: EXE,
    existingRoboShortcutTarget: EXE.toUpperCase().replace(/\\/g, '/'),
    iconPath: ICON,
    packaged: false,
    programsDir: PROGRAMS
  })

  assert.equal(ours.shortcut?.path, `${PROGRAMS}\\Robo.lnk`)
})

test('from source without an icon or a Start menu: the id alone', () => {
  assert.equal(
    planWindowsAppIdentity({ appPath: APP, execPath: EXE, iconPath: null, packaged: false, programsDir: PROGRAMS })
      .shortcut,
    null
  )
  assert.equal(
    planWindowsAppIdentity({ appPath: APP, execPath: EXE, iconPath: ICON, packaged: false, programsDir: null })
      .shortcut,
    null
  )
  assert.equal(windowsAppUserModelId(false, EXE), ROBO_SOURCE_APP_USER_MODEL_ID)
  assert.equal(windowsAppUserModelId(true, 'C:\\Program Files\\Robo\\Robo.exe'), ROBO_APP_USER_MODEL_ID)
})

test('`robo desktop --source` runs the production bundle, which bakes packaged=true: electron.exe still counts as source', () => {
  // bundle-electron-main.mjs defines ROBO_DESKTOP_IS_PACKAGED=true in the
  // non-dev bundle so `electron .` loads dist/. The executable is the truth.
  assert.equal(isElectronBinary(EXE), true)
  assert.equal(isElectronBinary('C:/robo/node_modules/electron/dist/ELECTRON.EXE'), true)
  assert.equal(isElectronBinary('/home/ahmad/robo/node_modules/electron/dist/electron'), true)
  assert.equal(isElectronBinary('C:\\Program Files\\Robo\\Robo.exe'), false)
  assert.equal(isElectronBinary('C:\\robo\\release\\win-unpacked\\Robo.exe'), false)

  assert.equal(runsFromSource(true, EXE), true)
  assert.equal(runsFromSource(false, 'C:\\Program Files\\Robo\\Robo.exe'), true)
  assert.equal(runsFromSource(true, 'C:\\Program Files\\Robo\\Robo.exe'), false)

  const plan = planWindowsAppIdentity({
    appPath: APP,
    execPath: EXE,
    iconPath: ICON,
    packaged: true,
    programsDir: PROGRAMS
  })

  assert.equal(plan.appUserModelId, ROBO_SOURCE_APP_USER_MODEL_ID)
  assert.equal(plan.shortcut?.path, `${PROGRAMS}\\Robo.lnk`)
  assert.equal(plan.shortcut?.options.icon, ICON)
  assert.equal(windowsAppUserModelId(true, EXE), ROBO_SOURCE_APP_USER_MODEL_ID)
})

test('shortcutMatches: rewrite only when target, icon, args or id changed', () => {
  const wanted = planWindowsAppIdentity({
    appPath: APP,
    execPath: EXE,
    iconPath: ICON,
    packaged: false,
    programsDir: PROGRAMS
  }).shortcut!.options

  assert.equal(shortcutMatches(null, wanted), false)
  assert.equal(shortcutMatches({ ...wanted }, wanted), true)
  assert.equal(shortcutMatches({ ...wanted, target: EXE.toLowerCase() }, wanted), true)
  assert.equal(shortcutMatches({ ...wanted, icon: 'C:\\old\\icon.ico' }, wanted), false)
  assert.equal(shortcutMatches({ ...wanted, appUserModelId: ROBO_APP_USER_MODEL_ID }, wanted), false)
  assert.equal(shortcutMatches({ ...wanted, args: '' }, wanted), false)
})

test('windowsStartMenuProgramsDir: under %APPDATA%, or unknown', () => {
  assert.equal(
    windowsStartMenuProgramsDir({ APPDATA: 'C:\\Users\\ahmad\\AppData\\Roaming' }),
    'C:\\Users\\ahmad\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs'
  )
  assert.equal(windowsStartMenuProgramsDir({}), null)
  assert.equal(windowsStartMenuProgramsDir({ APPDATA: '  ' }), null)
})
