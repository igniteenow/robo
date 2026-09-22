/**
 * Pure helpers for choosing a configured Robo update remote.
 *
 * Robo release packages do not inherit a third-party update source. A future
 * deployment may explicitly provide ROBO_UPDATE_REPO_URL, but the default is
 * intentionally empty so a packaged build never replaces itself from an
 * unrelated repository.
 */

const OFFICIAL_REPO_HTTPS_URL = String(process.env.ROBO_UPDATE_REPO_URL || '').trim()
const OFFICIAL_REPO_CANONICAL = canonicalGitHubRemote(OFFICIAL_REPO_HTTPS_URL)

// Normalize common GitHub remote URL forms to `host/owner/repo` (lowercased,
// no trailing slash, no .git suffix) so SSH and HTTPS forms of the same repo
// compare equal.
function canonicalGitHubRemote(url) {
  if (!url) {
    return ''
  }

  let value = String(url).trim()

  if (value.startsWith('git@github.com:')) {
    value = `github.com/${value.slice('git@github.com:'.length)}`
  } else if (value.startsWith('ssh://git@github.com/')) {
    value = `github.com/${value.slice('ssh://git@github.com/'.length)}`
  } else {
    try {
      const parsed = new URL(value)

      if (parsed.hostname && parsed.pathname) {
        value = `${parsed.hostname}${parsed.pathname}`
      }
    } catch {
      // Leave non-URL forms unchanged.
    }
  }

  value = value.trim().replace(/\/+$/, '')

  if (value.endsWith('.git')) {
    value = value.slice(0, -4)
  }

  return value.toLowerCase()
}

function isSshRemote(url) {
  const value = String(url || '')
    .trim()
    .toLowerCase()

  return value.startsWith('git@') || value.startsWith('ssh://')
}

function isOfficialSshRemote(url) {
  return Boolean(OFFICIAL_REPO_CANONICAL) && isSshRemote(url) && canonicalGitHubRemote(url) === OFFICIAL_REPO_CANONICAL
}

export { canonicalGitHubRemote, isOfficialSshRemote, isSshRemote, OFFICIAL_REPO_CANONICAL, OFFICIAL_REPO_HTTPS_URL }
