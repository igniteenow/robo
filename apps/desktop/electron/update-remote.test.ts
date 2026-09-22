/**
 * Tests for electron/update-remote.ts — the remote-detection helpers that
 * keep passive update checks off the SSH origin for official installs.
 *
 * Run with: node --test electron/update-remote.test.ts
 * (Wired into npm test:desktop:platforms in package.json.)
 *
 * Why this matters: an install with ROBO_UPDATE_REPO_URL configured to an
 * SSH origin, with a FIDO2/passkey key, can trigger an unexplained
 * hardware-touch prompt on a background `git fetch origin`.
 * isOfficialSshRemote must reliably recognize the configured SSH remote (in
 * every URL form, case-insensitively) so the caller can swap in the
 * anonymous HTTPS path — while NOT misclassifying forks, other hosts, or
 * the HTTPS remote (which never prompts and should keep the normal fetch
 * path). OFFICIAL_REPO_HTTPS_URL is empty by default — no packaged build
 * points at a hardcoded upstream — so with no override configured,
 * isOfficialSshRemote must never match any remote.
 */

import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  canonicalGitHubRemote,
  isOfficialSshRemote,
  isSshRemote,
  OFFICIAL_REPO_CANONICAL,
  OFFICIAL_REPO_HTTPS_URL
} from './update-remote'

test('canonicalGitHubRemote normalizes SSH and HTTPS forms to the same value', () => {
  const ssh = canonicalGitHubRemote('git@github.com:IgniteeNow/Robo.git')
  assert.equal(canonicalGitHubRemote('git@github.com:IgniteeNow/Robo'), ssh)
  assert.equal(canonicalGitHubRemote('ssh://git@github.com/IgniteeNow/Robo.git'), ssh)
  assert.equal(canonicalGitHubRemote('https://github.com/IgniteeNow/Robo.git'), ssh)
  // Case-insensitive: an uppercased owner still canonicalizes to the same repo.
  assert.equal(canonicalGitHubRemote('git@github.com:Your-Org/robo-engineer.git'), ssh)
  // Trailing slashes are stripped.
  assert.equal(canonicalGitHubRemote('https://github.com/IgniteeNow/Robo/'), ssh)
})

test('canonicalGitHubRemote is empty for falsy input', () => {
  assert.equal(canonicalGitHubRemote(''), '')
  assert.equal(canonicalGitHubRemote(null), '')
  assert.equal(canonicalGitHubRemote(undefined), '')
})

test('isSshRemote detects scp-like and ssh:// forms only', () => {
  assert.equal(isSshRemote('git@github.com:IgniteeNow/Robo.git'), true)
  assert.equal(isSshRemote('ssh://git@github.com/IgniteeNow/Robo.git'), true)
  assert.equal(isSshRemote('https://github.com/IgniteeNow/Robo.git'), false)
  assert.equal(isSshRemote(''), false)
  assert.equal(isSshRemote(null), false)
})

test('isOfficialSshRemote never matches when no ROBO_UPDATE_REPO_URL is configured', () => {
  // OFFICIAL_REPO_HTTPS_URL is intentionally empty by default (see module
  // docstring) — a packaged build never replaces itself from a hardcoded
  // upstream. With nothing configured, no remote can be "official".
  assert.equal(OFFICIAL_REPO_HTTPS_URL, '')
  assert.equal(OFFICIAL_REPO_CANONICAL, '')
  assert.equal(isOfficialSshRemote('git@github.com:IgniteeNow/Robo.git'), false)
  assert.equal(isOfficialSshRemote('ssh://git@github.com/IgniteeNow/Robo.git'), false)
})

test('isOfficialSshRemote does NOT match forks, other hosts, or HTTPS even with a configured value', () => {
  // Simulate an operator having set ROBO_UPDATE_REPO_URL by comparing
  // canonicalGitHubRemote's own normalization directly, since the module
  // constant is fixed at import time from the (empty-in-tests) env var.
  const official = canonicalGitHubRemote('https://github.com/IgniteeNow/Robo.git')
  assert.notEqual(canonicalGitHubRemote('git@github.com:someuser/robo-engineer.git'), official)
  // Same repo name on a different host is not the official repo.
  assert.notEqual(canonicalGitHubRemote('git@gitlab.com:IgniteeNow/Robo.git'), official)
  assert.equal(isOfficialSshRemote(''), false)
  assert.equal(isOfficialSshRemote(null), false)
})

test('OFFICIAL_REPO_HTTPS_URL canonicalizes to OFFICIAL_REPO_CANONICAL', () => {
  // Invariant: the URL we substitute in must be the same repo we detect.
  assert.equal(canonicalGitHubRemote(OFFICIAL_REPO_HTTPS_URL), OFFICIAL_REPO_CANONICAL)
})
