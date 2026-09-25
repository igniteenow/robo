import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'vitest'

import {
  brandDevElectron,
  describeBrandFailure,
  resolveDevElectronBinary,
  shouldBrandDevElectron
} from '../scripts/brand-dev-electron.mjs'

// The from-source Electron binary gets Robo's icon stamped in on Windows so
// the taskbar shows Robo, not the Electron atom. Never on other platforms,
// never when opted out, and never as a build failure.

test('brands only on Windows, and not when opted out', () => {
  assert.equal(shouldBrandDevElectron('win32', {}), true)
  assert.equal(shouldBrandDevElectron('darwin', {}), false)
  assert.equal(shouldBrandDevElectron('linux', {}), false)
  assert.equal(shouldBrandDevElectron('win32', { ROBO_DESKTOP_SKIP_EXE_BRAND: '1' }), false)
  assert.equal(shouldBrandDevElectron('win32', { ROBO_DESKTOP_SKIP_EXE_BRAND: 'true' }), false)
  assert.equal(shouldBrandDevElectron('win32', { ROBO_DESKTOP_SKIP_EXE_BRAND: '0' }), true)
})

test('resolves the electron binary the package would launch, or nothing', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'robo-brand-'))
  const exe = path.join(tempRoot, 'electron.exe')

  try {
    fs.writeFileSync(exe, 'MZ')
    assert.equal(resolveDevElectronBinary(() => exe), exe)
    assert.equal(resolveDevElectronBinary(() => path.join(tempRoot, 'missing.exe')), null)
    assert.equal(
      resolveDevElectronBinary(() => {
        throw new Error('not installed')
      }),
      null
    )
    assert.equal(resolveDevElectronBinary(() => ({ app: {} })), null)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('a locked binary is explained, not thrown', () => {
  assert.match(describeBrandFailure(new Error('EBUSY: resource busy or locked')), /close the running Robo window/)
  assert.match(describeBrandFailure(new Error('Access is denied.')), /close the running Robo window/)
  assert.equal(describeBrandFailure(new Error('rcedit exited with code 1')), 'rcedit exited with code 1')
})

test('off Windows the step is a no-op and the build goes on', async () => {
  const warnings = []
  const result = await brandDevElectron({ log: { warn: line => warnings.push(line) }, platform: 'linux', env: {} })

  assert.deepEqual(result, { skipped: 'not windows' })
  assert.deepEqual(warnings, [])
})
