// Unit tests for the pure Windows `robo` resolution helpers extracted from
// main.ts's findOnPath(), handOffWindowsBootstrapRecovery(), and
// unwrapWindowsVenvRoboCommand(). These pin the two Windows resolution bugs
// that caused desktop reinstall loops:
//   1. buildPathExtCandidates() — PATHEXT extensions must be tried BEFORE the
//      empty extension, or an extensionless Git-Bash `robo` shim shadows
//      the real robo.cmd/robo.exe.
//   2. chooseUpdaterArgs() — must gate on haveRealInstall (any real-install
//      signal), not just the robo.exe console-script shim, or healthy
//      installs get forced into a destructive --repair.
//   3. resolveVenvRoboCommand() — must probe the venv python via
//      canImportRoboCli() before trusting it, or a broken venv gets
//      re-selected forever instead of falling through to bootstrap.

import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import {
  buildPathExtCandidates,
  chooseUpdaterArgs,
  getVenvSitePackagesEntries,
  resolveVenvRoboCommand
} from './windows-robo-path'

test('buildPathExtCandidates: Windows tries PATHEXT extensions before the empty extension', () => {
  const extensions = buildPathExtCandidates('.COM;.EXE;.BAT;.CMD', true)

  assert.deepEqual(extensions, ['.COM', '.EXE', '.BAT', '.CMD', ''])
  assert.equal(extensions[extensions.length - 1], '', 'empty extension must be last, not first')
  assert.notEqual(extensions[0], '', 'the buggy empty-extension-first order must not return')
})

test('buildPathExtCandidates: defaults to .COM;.EXE;.BAT;.CMD when PATHEXT is unset on Windows', () => {
  assert.deepEqual(buildPathExtCandidates(undefined, true), ['.COM', '.EXE', '.BAT', '.CMD', ''])
})

test('buildPathExtCandidates: respects a custom PATHEXT, still empty-last', () => {
  assert.deepEqual(buildPathExtCandidates('.EXE;.PS1', true), ['.EXE', '.PS1', ''])
})

test('buildPathExtCandidates: non-Windows only tries the bare name', () => {
  assert.deepEqual(buildPathExtCandidates('.COM;.EXE;.BAT;.CMD', false), [''])
  assert.deepEqual(buildPathExtCandidates(undefined, false), [''])
})

test('chooseUpdaterArgs: gentle --update when a real-install signal is present', () => {
  assert.deepEqual(chooseUpdaterArgs(true, 'main'), ['--update', '--branch', 'main'])
})

test('chooseUpdaterArgs: destructive --repair only when NO real-install signal is present', () => {
  assert.deepEqual(chooseUpdaterArgs(false, 'main'), ['--repair', '--branch', 'main'])
})

test('chooseUpdaterArgs: passes the branch through unchanged in both cases', () => {
  assert.deepEqual(chooseUpdaterArgs(true, 'release/1.2'), ['--update', '--branch', 'release/1.2'])
  assert.deepEqual(chooseUpdaterArgs(false, 'release/1.2'), ['--repair', '--branch', 'release/1.2'])
})

function makeDeps(overrides: Partial<Parameters<typeof resolveVenvRoboCommand>[2]> = {}) {
  return {
    isWindows: true,
    isCommandScript: () => false,
    fileExists: () => true,
    directoryExists: () => false,
    canImportRoboCli: () => true,
    getVenvPython: (venvRoot: string) => `${venvRoot}/Scripts/python.exe`,
    getVenvSitePackagesEntries: () => [],
    buildDesktopBackendEnv: () => ({ FAKE_ENV: '1' }),
    roboHome: '/fake/robo-home',
    resolvePath: (...segments: string[]) => segments.join('/').replace(/\/+/g, '/'),
    dirname: (p: string) => p.slice(0, p.lastIndexOf('/')) || '/',
    basename: (p: string) => p.slice(p.lastIndexOf('/') + 1),
    rememberLog: () => {},
    ...overrides
  }
}

test('resolveVenvRoboCommand: returns null off Windows', () => {
  const deps = makeDeps({ isWindows: false })

  assert.equal(resolveVenvRoboCommand('/root/venv/Scripts/robo.exe', [], deps), null)
})

test('resolveVenvRoboCommand: returns null for a .cmd/.bat script command', () => {
  const deps = makeDeps({ isCommandScript: () => true })

  assert.equal(resolveVenvRoboCommand('/root/venv/Scripts/robo.cmd', [], deps), null)
})

test('resolveVenvRoboCommand: returns null when the basename is not robo/robo.exe', () => {
  const deps = makeDeps()

  assert.equal(resolveVenvRoboCommand('/root/venv/Scripts/python.exe', [], deps), null)
})

test('resolveVenvRoboCommand: returns null when the parent dir is not Scripts', () => {
  const deps = makeDeps()

  assert.equal(resolveVenvRoboCommand('/root/venv/bin/robo.exe', [], deps), null)
})

test('resolveVenvRoboCommand: returns null when the venv python does not exist on disk', () => {
  const deps = makeDeps({ fileExists: () => false })

  assert.equal(resolveVenvRoboCommand('/root/venv/Scripts/robo.exe', [], deps), null)
})

test('resolveVenvRoboCommand: probes the venv python before trusting it (returns null on failed probe)', () => {
  let probed = false

  const deps = makeDeps({
    canImportRoboCli: (python: string) => {
      probed = true
      assert.equal(python, '/root/venv/Scripts/python.exe')

      return false
    }
  })

  const result = resolveVenvRoboCommand('/root/venv/Scripts/robo.exe', ['serve'], deps)

  assert.equal(probed, true, 'must probe the venv interpreter; a broken venv must not be re-selected forever')
  assert.equal(result, null, 'a failed probe must fall through (return null) so the resolver reaches bootstrap')
})

test('resolveVenvRoboCommand: returns the resolved python backend descriptor when the probe passes', () => {
  const deps = makeDeps()
  const result = resolveVenvRoboCommand('/root/venv/Scripts/robo.exe', ['serve', '--port', '0'], deps)

  assert.ok(result, 'a passing probe must return a backend descriptor, not null')
  assert.equal(result.command, '/root/venv/Scripts/python.exe')
  assert.deepEqual(result.args, ['-m', 'robo_cli.main', 'serve', '--port', '0'])
  assert.equal(result.bootstrap, false)
  assert.equal(result.kind, 'python')
  assert.equal(result.shell, false)
  assert.deepEqual(result.env, { FAKE_ENV: '1' })
})

test('resolveVenvRoboCommand: is case-insensitive on robo.exe and the Scripts dir name', () => {
  const deps = makeDeps()

  assert.ok(resolveVenvRoboCommand('/root/venv/Scripts/ROBO.EXE', [], deps))
  assert.ok(resolveVenvRoboCommand('/root/venv/SCRIPTS/robo.exe', [], deps))
})

// ── getVenvSitePackagesEntries ─────────────────────────────────────────────

test('getVenvSitePackagesEntries: returns Lib/site-packages on Windows when it exists', () => {
  const expected = path.join('C:\\venv', 'Lib', 'site-packages')

  const result = getVenvSitePackagesEntries('C:\\venv', {
    isWindows: true,
    directoryExists: p => p === expected
  })

  assert.deepEqual(result, [expected])
})

test('getVenvSitePackagesEntries: returns empty on Windows when site-packages does not exist', () => {
  const result = getVenvSitePackagesEntries('C:\\venv', {
    isWindows: true,
    directoryExists: () => false
  })

  assert.deepEqual(result, [])
})

test('getVenvSitePackagesEntries: reads pyvenv.cfg version on POSIX and resolves lib/pythonX.Y/site-packages', () => {
  const result = getVenvSitePackagesEntries('/venv', {
    isWindows: false,
    directoryExists: p => p === '/venv/lib/python3.12/site-packages',
    readFile: () => 'version_info = 3.12.1\n'
  })

  assert.deepEqual(result, ['/venv/lib/python3.12/site-packages'])
})

test('getVenvSitePackagesEntries: returns empty on POSIX when pyvenv.cfg is missing', () => {
  const result = getVenvSitePackagesEntries('/venv', {
    isWindows: false,
    directoryExists: () => true,
    readFile: () => undefined
  })

  assert.deepEqual(result, [])
})

test('getVenvSitePackagesEntries: returns empty on POSIX when pyvenv.cfg has no version_info', () => {
  const result = getVenvSitePackagesEntries('/venv', {
    isWindows: false,
    directoryExists: () => true,
    readFile: () => 'home = /usr/bin\n'
  })

  assert.deepEqual(result, [])
})

test('getVenvSitePackagesEntries: returns empty on POSIX when version is present but site-packages dir is absent', () => {
  const result = getVenvSitePackagesEntries('/venv', {
    isWindows: false,
    directoryExists: () => false,
    readFile: () => 'version_info = 3.11\n'
  })

  assert.deepEqual(result, [])
})

test('getVenvSitePackagesEntries: returns empty for a falsy venvRoot', () => {
  assert.deepEqual(getVenvSitePackagesEntries('', { isWindows: true, directoryExists: () => true }), [])
  assert.deepEqual(getVenvSitePackagesEntries(null, { isWindows: true, directoryExists: () => true }), [])
  assert.deepEqual(getVenvSitePackagesEntries(undefined, { isWindows: true, directoryExists: () => true }), [])
})
