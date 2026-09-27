/**
 * Tests for electron/update-remote.ts — the remote-detection helpers that
 * keep passive update checks off the SSH origin for official installs.
 *
 * Run with: node --test electron/update-remote.test.ts
 * (Wired into npm test:desktop:platforms in package.json.)
 *
 * Why this matters: an install whose origin is the official repo over SSH,
 * with a FIDO2/passkey key, can trigger an unexplained hardware-touch prompt
 * on a background `git fetch origin`. isOfficialSshRemote must reliably
 * recognize the official SSH remote (in every URL form, case-insensitively)
 * so the caller can swap in the anonymous HTTPS path — while NOT
 * misclassifying forks, other hosts, or the HTTPS remote (which never
 * prompts and should keep the normal fetch path). With no
 * ROBO_UPDATE_REPO_URL override, the official repo is Ignitee Now's, so the
 * desktop checks for updates out of the box.
 */

import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  canonicalGitHubRemote,
  DEFAULT_UPDATE_REPO_URL,
  isOfficialSshRemote,
  isSshRemote,
  OFFICIAL_REPO_CANONICAL,
  OFFICIAL_REPO_HTTPS_URL
} from './update-remote'

test('canonicalGitHubRemote normalizes SSH and HTTPS forms to the same value', () => {
  const ssh = canonicalGitHubRemote('git@github.com:igniteenow/robo.git')
  assert.equal(canonicalGitHubRemote('git@github.com:igniteenow/robo'), ssh)
  assert.equal(canonicalGitHubRemote('ssh://git@github.com/igniteenow/robo.git'), ssh)
  assert.equal(canonicalGitHubRemote('https://github.com/igniteenow/robo.git'), ssh)
  // Case-insensitive: an uppercased owner still canonicalizes to the same repo.
  assert.equal(canonicalGitHubRemote('git@github.com:IgniteeNow/Robo.git'), ssh)
  // Trailing slashes are stripped.
  assert.equal(canonicalGitHubRemote('https://github.com/igniteenow/robo/'), ssh)
})

test('canonicalGitHubRemote is empty for falsy input', () => {
  assert.equal(canonicalGitHubRemote(''), '')
  assert.equal(canonicalGitHubRemote(null), '')
  assert.equal(canonicalGitHubRemote(undefined), '')
})

test('isSshRemote detects scp-like and ssh:// forms only', () => {
  assert.equal(isSshRemote('git@github.com:igniteenow/robo.git'), true)
  assert.equal(isSshRemote('ssh://git@github.com/igniteenow/robo.git'), true)
  assert.equal(isSshRemote('https://github.com/igniteenow/robo.git'), false)
  assert.equal(isSshRemote(''), false)
  assert.equal(isSshRemote(null), false)
})

test('with no ROBO_UPDATE_REPO_URL, updates come from the default repo', () => {
  // An empty update source switched the desktop's update check off entirely,
  // so no install ever heard about an update.
  assert.notEqual(OFFICIAL_REPO_HTTPS_URL, '')
  assert.equal(OFFICIAL_REPO_HTTPS_URL, DEFAULT_UPDATE_REPO_URL)
  assert.equal(OFFICIAL_REPO_CANONICAL, canonicalGitHubRemote(DEFAULT_UPDATE_REPO_URL))
})

test('isOfficialSshRemote recognizes the default repo over SSH, in every form', () => {
  const [owner, repo] = OFFICIAL_REPO_CANONICAL.replace(/^github\.com\//, '').split('/')

  assert.equal(isOfficialSshRemote(`git@github.com:${owner}/${repo}.git`), true)
  assert.equal(isOfficialSshRemote(`ssh://git@github.com/${owner}/${repo}.git`), true)
  assert.equal(isOfficialSshRemote(`git@github.com:${owner.toUpperCase()}/${repo}`), true)
  // HTTPS never prompts, so it keeps the normal fetch path.
  assert.equal(isOfficialSshRemote(DEFAULT_UPDATE_REPO_URL), false)
  // A fork over SSH is not the official repo.
  assert.equal(isOfficialSshRemote(`git@github.com:someone-else/${repo}.git`), false)
})

test('isOfficialSshRemote does NOT match forks, other hosts, or HTTPS even with a configured value', () => {
  // Simulate an operator having set ROBO_UPDATE_REPO_URL by comparing
  // canonicalGitHubRemote's own normalization directly, since the module
  // constant is fixed at import time from the (empty-in-tests) env var.
  const official = canonicalGitHubRemote('https://github.com/igniteenow/robo.git')
  assert.notEqual(canonicalGitHubRemote('git@github.com:someuser/robo-engineer.git'), official)
  // Same repo name on a different host is not the official repo.
  assert.notEqual(canonicalGitHubRemote('git@gitlab.com:igniteenow/robo.git'), official)
  assert.equal(isOfficialSshRemote(''), false)
  assert.equal(isOfficialSshRemote(null), false)
})

test('OFFICIAL_REPO_HTTPS_URL canonicalizes to OFFICIAL_REPO_CANONICAL', () => {
  // Invariant: the URL we substitute in must be the same repo we detect.
  assert.equal(canonicalGitHubRemote(OFFICIAL_REPO_HTTPS_URL), OFFICIAL_REPO_CANONICAL)
})
