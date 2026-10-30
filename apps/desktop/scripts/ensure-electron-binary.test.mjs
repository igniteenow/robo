import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'vitest'

import {
  electronDistBinary,
  ensureElectronBinary,
  resolveElectronDir,
  shouldSkipElectronDownload
} from '../scripts/ensure-electron-binary.mjs'

// Electron 42 stopped downloading its binary on install. The desktop
// workspace's postinstall does it instead, so node_modules/electron/dist is in
// place after `npm ci` exactly as before (electron-builder, `robo desktop` and
// the installers all expect it there).

const quiet = { log() {}, warn() {} }

function fakeElectron({ installer = true } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'robo-electron-'))

  if (installer) {
    fs.writeFileSync(path.join(dir, 'install.js'), '')
  }

  return dir
}

function placeBinary(dir, platform) {
  const binary = electronDistBinary(dir, platform)
  fs.mkdirSync(path.dirname(binary), { recursive: true })
  fs.writeFileSync(binary, '')
}

test('the binary path matches what electron-builder and robo desktop look for', () => {
  assert.equal(electronDistBinary('/e', 'win32'), path.join('/e', 'dist', 'electron.exe'))
  assert.equal(electronDistBinary('/e', 'linux'), path.join('/e', 'dist', 'electron'))
  assert.equal(
    electronDistBinary('/e', 'darwin'),
    path.join('/e', 'dist', 'Electron.app', 'Contents', 'MacOS', 'Electron')
  )
})

test('skips on request, like ELECTRON_SKIP_BINARY_DOWNLOAD did before Electron 42', () => {
  assert.equal(shouldSkipElectronDownload({}), false)
  assert.equal(shouldSkipElectronDownload({ ELECTRON_SKIP_BINARY_DOWNLOAD: '1' }), true)
  assert.equal(shouldSkipElectronDownload({ ROBO_DESKTOP_SKIP_ELECTRON_DOWNLOAD: 'true' }), true)
  assert.equal(shouldSkipElectronDownload({ ELECTRON_SKIP_BINARY_DOWNLOAD: '0' }), false)

  let ran = false
  const result = ensureElectronBinary({
    env: { ELECTRON_SKIP_BINARY_DOWNLOAD: '1' },
    log: quiet,
    electronDir: fakeElectron(),
    run: () => {
      ran = true

      return 0
    }
  })

  assert.deepEqual(result, { skipped: 'env' })
  assert.equal(ran, false)
})

test('does nothing when the binary is already there', () => {
  const dir = fakeElectron()
  placeBinary(dir, 'linux')
  let ran = false

  const result = ensureElectronBinary({
    env: {},
    log: quiet,
    platform: 'linux',
    electronDir: dir,
    run: () => {
      ran = true

      return 0
    }
  })

  assert.deepEqual(result, { present: true })
  assert.equal(ran, false)
})

test("runs electron's own installer from its folder when the binary is missing", () => {
  const dir = fakeElectron()
  const calls = []

  const result = ensureElectronBinary({
    env: {},
    log: quiet,
    platform: 'win32',
    electronDir: dir,
    run: (installer, cwd) => {
      calls.push([installer, cwd])
      placeBinary(dir, 'win32')

      return 0
    }
  })

  assert.deepEqual(result, { downloaded: true })
  assert.deepEqual(calls, [[path.join(dir, 'install.js'), dir]])
})

test('fails the install when the download fails, so the existing repair paths take over', () => {
  const failed = ensureElectronBinary({
    env: {},
    log: quiet,
    platform: 'linux',
    electronDir: fakeElectron(),
    run: () => 7
  })

  assert.deepEqual(failed, { failed: 'download', status: 7 })

  // Exit 0 but still no binary is a failure too.
  const empty = ensureElectronBinary({
    env: {},
    log: quiet,
    platform: 'linux',
    electronDir: fakeElectron(),
    run: () => 0
  })

  assert.deepEqual(empty, { failed: 'download', status: 1 })

  const noInstaller = ensureElectronBinary({
    env: {},
    log: quiet,
    platform: 'linux',
    electronDir: fakeElectron({ installer: false }),
    run: () => 0
  })

  assert.deepEqual(noInstaller, { failed: 'no installer', status: 1 })
})

test('an install without electron (production deps only) is not an error', () => {
  assert.deepEqual(ensureElectronBinary({ env: {}, log: quiet, electronDir: null }), { skipped: 'not installed' })
  assert.equal(
    resolveElectronDir(
      Object.assign(() => null, {
        resolve: () => {
          throw new Error('Cannot find module')
        }
      })
    ),
    null
  )
})
