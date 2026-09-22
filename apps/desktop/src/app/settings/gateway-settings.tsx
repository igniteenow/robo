import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tip } from '@/components/ui/tooltip'
import type { DesktopAuthProvider, DesktopConnectionProbeResult } from '@/global'
import { useI18n } from '@/i18n'
import { ExternalLink } from '@/lib/external-link'
import {
  AlertCircle,
  Check,
  FileText,
  Globe,
  HelpCircle,
  Loader2,
  LogIn,
  Monitor,
  RefreshCw,
  Terminal
} from '@/lib/icons'
import { coerceRemoteUrlScheme } from '@/lib/remote-url'
import { selectableCardClass } from '@/lib/selectable-card'
import { cn } from '@/lib/utils'
import { notify, notifyError } from '@/store/notifications'
import { $profiles, refreshActiveProfile } from '@/store/profile'

import { CONTROL_TEXT } from './constants'
import { EmptyState, ListRow, Pill, SettingsContent, SettingsSkeleton } from './primitives'
import { enrichSelectedSshHost, selectSshHost } from './ssh-host-selection'

type Mode = 'local' | 'remote' | 'ssh'
type AuthMode = 'oauth' | 'token'
type ProbeStatus = 'idle' | 'probing' | 'done' | 'error'

interface GatewaySettingsState {
  envOverride: boolean
  mode: Mode
  remoteAuthMode: AuthMode
  remoteOauthConnected: boolean
  remoteTokenPreview: string | null
  remoteTokenSet: boolean
  remoteUrl: string
  sshHost: string
  sshUser: string
  sshPort: number | null
  sshKeyPath: string
  sshRemoteRoboPath: string
  sshRemoteProfile: string
}

const SSH_HOST_CUSTOM = '__custom__'

const EMPTY_STATE: GatewaySettingsState = {
  envOverride: false,
  mode: 'local',
  remoteAuthMode: 'token',
  remoteOauthConnected: false,
  remoteTokenPreview: null,
  remoteTokenSet: false,
  remoteUrl: '',
  sshHost: '',
  sshUser: '',
  sshPort: null,
  sshKeyPath: '',
  sshRemoteRoboPath: '',
  sshRemoteProfile: ''
}

function ModeCard({
  active,
  description,
  disabled,
  hint,
  icon: Icon,
  onSelect,
  title
}: {
  active: boolean
  description: string
  disabled?: boolean
  hint?: string
  icon: typeof Monitor
  onSelect: () => void
  title: string
}) {
  return (
    <button
      className={cn(
        'flex h-full min-h-0 w-full flex-col p-3 text-left disabled:cursor-not-allowed disabled:opacity-50',
        selectableCardClass({ active, prominent: true })
      )}
      disabled={disabled}
      onClick={onSelect}
      type="button"
    >
      <div className="flex items-center gap-1.5">
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 text-[length:var(--conversation-text-font-size)] font-medium">{title}</span>
        {hint ? (
          <Tip label={hint}>
            <span
              className="grid size-3.5 shrink-0 cursor-help place-items-center text-(--ui-text-tertiary) hover:text-(--ui-text-secondary)"
              onClick={event => event.stopPropagation()}
            >
              <HelpCircle className="size-3.5" />
            </span>
          </Tip>
        ) : null}
        {active ? <Check className="ml-auto size-3.5 shrink-0 text-primary" /> : null}
      </div>
      <p className="mt-1.5 flex-1 text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)">
        {description}
      </p>
    </button>
  )
}

function ScopeChip({ active, label, onSelect }: { active: boolean; label: string; onSelect: () => void }) {
  return (
    <button
      className={cn(
        'rounded-full border px-3 py-1 text-[length:var(--conversation-caption-font-size)] transition',
        active
          ? 'border-(--ui-stroke-secondary) bg-(--ui-bg-tertiary) text-(--ui-text-primary)'
          : 'border-(--ui-stroke-tertiary) bg-(--ui-bg-quinary) text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover)'
      )}
      onClick={onSelect}
      type="button"
    >
      {label}
    </button>
  )
}

// `embedded` trims the page chrome for reuse inside the boot-failure recovery
// card: the outer title/intro, the "Save for next restart" action, and the
// Diagnostics row are redundant there (the card owns its header + a single
// reconnect action), so only the connection controls render.
export function GatewaySettings({ embedded = false }: { embedded?: boolean } = {}) {
  const { t } = useI18n()
  const g = t.settings.gateway
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [signingIn, setSigningIn] = useState(false)
  const [state, setState] = useState<GatewaySettingsState>(EMPTY_STATE)
  const [remoteToken, setRemoteToken] = useState('')
  const [lastTest, setLastTest] = useState<null | string>(null)
  const [sshHostSuggestions, setSshHostSuggestions] = useState<string[]>([])
  const [sshCustomHost, setSshCustomHost] = useState(false)
  const sshResolveSeq = useRef(0)
  const sshTestSeq = useRef(0)
  const saveSeq = useRef(0)
  const signingSeq = useRef(0)
  const contextSeq = useRef(0)

  const acceptSavedConfig = (config: GatewaySettingsState) => {
    setState(config)
  }

  // Connection scope: null = the global/default connection (the original
  // behavior); a profile name = that profile's per-profile remote override, so
  // each profile can point at its own backend.
  const [scope, setScope] = useState<null | string>(null)
  const profiles = useStore($profiles)

  useEffect(() => {
    void refreshActiveProfile()
  }, [])

  // Auth-mode probe: as the user types a remote URL we ask the gateway (via
  // its public /api/status) whether it gates with OAuth or a static session
  // token, so we can show the right control (login button vs token box).
  const [probeStatus, setProbeStatus] = useState<ProbeStatus>('idle')
  const [probe, setProbe] = useState<DesktopConnectionProbeResult | null>(null)
  const probeSeq = useRef(0)

  useEffect(() => {
    let cancelled = false
    const desktop = window.roboDesktop

    if (!desktop?.getConnectionConfig) {
      setLoading(false)

      return () => void (cancelled = true)
    }

    setLoading(true)
    // Clear scope-local entry state so a token from one scope can't leak into
    // the next when switching profiles.
    setRemoteToken('')
    setLastTest(null)

    desktop
      .getConnectionConfig(scope)
      .then(config => {
        if (cancelled) {
          return
        }

        acceptSavedConfig(config)
      })
      .catch(err => notifyError(err, g.failedLoad))
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => void (cancelled = true)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on scope change only; copy is stable
  }, [scope])

  // Debounced probe of the entered remote URL. Only runs in remote mode with a
  // syntactically plausible URL. The probe result drives whether we render the
  // OAuth login button or the session-token entry box. The effective auth mode
  // prefers a fresh probe result over the saved value.
  const trimmedUrl = coerceRemoteUrlScheme(state.remoteUrl)

  useEffect(() => {
    if (state.mode !== 'remote' || !trimmedUrl || !/^https?:\/\//i.test(trimmedUrl)) {
      setProbeStatus('idle')
      setProbe(null)

      return
    }

    const desktop = window.roboDesktop

    if (!desktop?.probeConnectionConfig) {
      return
    }

    const seq = ++probeSeq.current
    setProbeStatus('probing')

    const timer = setTimeout(() => {
      desktop
        .probeConnectionConfig(trimmedUrl)
        .then(result => {
          if (seq !== probeSeq.current) {
            return
          }

          setProbe(result)
          setProbeStatus(result.reachable ? 'done' : 'error')
        })
        .catch(() => {
          if (seq !== probeSeq.current) {
            return
          }

          setProbe(null)
          setProbeStatus('error')
        })
    }, 500)

    return () => clearTimeout(timer)
  }, [state.mode, trimmedUrl])

  // Effective auth mode: a reachable probe wins; otherwise fall back to the
  // saved config's mode so a re-open of settings doesn't flicker.
  const authMode: AuthMode = useMemo(() => {
    if (probeStatus === 'done' && probe && probe.authMode !== 'unknown') {
      return probe.authMode
    }

    return state.remoteAuthMode
  }, [probe, probeStatus, state.remoteAuthMode])

  // Whether we actually KNOW how this gateway authenticates yet. Until we do,
  // neither the OAuth button nor the session-token box should render —
  // `authMode` defaults to 'token', so without this gate the token box flashes
  // for every gateway (including OAuth ones) during the idle/probing window
  // before the first probe lands. The scheme is known when either:
  //   * the live probe finished (probeStatus 'done'), or
  //   * we're idle but showing a previously-saved remote config (re-opening
  //     settings for a gateway already signed-in or with a saved token), so
  //     its control appears immediately with no flicker.
  // While probing (or after a probe error), the scheme is unknown and we show
  // the probe status row instead of a control.
  const hasSavedRemote = state.remoteTokenSet || state.remoteOauthConnected

  const authResolved = useMemo(() => {
    if (probeStatus === 'done') {
      return true
    }

    return probeStatus === 'idle' && hasSavedRemote
  }, [probeStatus, hasSavedRemote])

  const providerLabel = useMemo(() => {
    const providers: DesktopAuthProvider[] = probe?.providers ?? []

    if (providers.length === 1) {
      return providers[0].displayName || providers[0].name
    }

    if (providers.length > 1) {
      return providers.map(p => p.displayName || p.name).join(' / ')
    }

    return t.boot.failure.identityProvider
  }, [probe, t.boot.failure.identityProvider])

  // A username/password gateway authenticates through a credential form on the
  // gateway's /login page (POST /auth/password-login) rather than an OAuth
  // redirect. Everything downstream — the session cookie, the ws-ticket mint,
  // the persistent partition — is identical, so the desktop drives it through
  // the same sign-in window; only the button copy changes. We treat the
  // gateway as password-style only when EVERY advertised provider supports
  // password, so a mixed deployment keeps the generic OAuth copy.
  const isPasswordProvider = useMemo(() => {
    const providers: DesktopAuthProvider[] = probe?.providers ?? []

    return providers.length > 0 && providers.every(p => p.supportsPassword)
  }, [probe])

  // The 'default' profile uses the global ("All profiles") connection, so the
  // per-profile scopes are the named, non-default profiles.
  const namedProfiles = useMemo(() => profiles.filter(profile => profile.name !== 'default'), [profiles])

  useEffect(() => {
    // One-directional: a saved host that isn't in the suggestions must render
    // the free-text input (rehydration). Never force custom OFF here — that
    // instantly snapped the just-clicked-Custom (empty-host) input back to the
    // dropdown, making a raw-IP host impossible to type. The way back to the
    // dropdown is the input's onBlur (empty host + suggestions).
    if (state.sshHost && !sshHostSuggestions.includes(state.sshHost)) {
      setSshCustomHost(true)
    }
  }, [state.sshHost, sshHostSuggestions])

  useEffect(() => {
    if (state.mode !== 'ssh' || !window.roboDesktop?.sshConfigHosts) {
      return
    }

    let cancelled = false
    void window.roboDesktop
      .sshConfigHosts()
      .then(result => {
        if (!cancelled) {
          setSshHostSuggestions(result.hosts)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSshHostSuggestions([])
        }
      })

    return () => void (cancelled = true)
  }, [state.mode])

  // eslint-disable-next-line no-restricted-syntax -- monotonic request-sequence counters, not an atom mirror
  useEffect(() => {
    contextSeq.current += 1
    sshTestSeq.current += 1
    saveSeq.current += 1
    signingSeq.current += 1
    setLastTest(null)
  }, [
    scope,
    state.mode,
    state.sshHost,
    state.sshUser,
    state.sshPort,
    state.sshKeyPath,
    state.sshRemoteRoboPath,
    state.sshRemoteProfile
  ])

  const oauthConnected = state.remoteOauthConnected

  const canUseRemote = useMemo(() => {
    if (!trimmedUrl) {
      return false
    }

    if (authMode === 'oauth') {
      return oauthConnected
    }

    return Boolean(remoteToken.trim()) || state.remoteTokenSet
  }, [authMode, oauthConnected, remoteToken, state.remoteTokenSet, trimmedUrl])

  const payload = () => ({
    mode: state.mode,
    profile: scope ?? undefined,
    remoteAuthMode: authMode,
    remoteToken: authMode === 'token' ? remoteToken.trim() || undefined : undefined,
    remoteUrl: trimmedUrl,
    sshHost: state.sshHost.trim(),
    sshUser: state.sshUser.trim() || undefined,
    sshPort: state.sshPort,
    sshKeyPath: state.sshKeyPath.trim() || undefined,
    sshRemoteRoboPath: state.sshRemoteRoboPath.trim(),
    // Preserve an intentional blank so an existing remote-profile mapping can
    // be cleared instead of being mistaken for an omitted field.
    sshRemoteProfile: state.sshRemoteProfile.trim()
  })

  const save = async (apply: boolean) => {
    const seq = ++saveSeq.current

    if (state.mode === 'remote' && !canUseRemote) {
      notify({
        kind: 'warning',
        title: g.incompleteTitle,
        message: authMode === 'oauth' ? g.incompleteSignIn : g.incompleteToken
      })

      return
    }

    setSaving(true)

    try {
      const next = apply
        ? await window.roboDesktop.applyConnectionConfig(payload())
        : await window.roboDesktop.saveConnectionConfig(payload())

      if (seq !== saveSeq.current) {
        return
      }

      acceptSavedConfig(next)
      setRemoteToken('')
      notify({
        kind: 'success',
        title: apply ? g.restartingTitle : g.savedTitle,
        message: apply ? g.restartingMessage : g.savedMessage
      })
    } catch (err) {
      if (seq !== saveSeq.current) {
        return
      }

      const sshError = err && typeof err === 'object' && 'sshError' in err ? String(err.sshError) : ''

      const errors = {
        'auth-failed': g.sshErrAuth,
        'robo-not-found': g.sshErrNotInstalled,
        'host-key-changed': g.sshErrHostKey,
        timeout: g.sshErrTimeout,
        unreachable: g.sshErrUnreachable,
        'unsupported-platform': g.sshErrPlatform,
        'update-required': g.sshErrUpdateRequired
      }

      if (state.mode === 'ssh' && sshError) {
        notify({
          kind: 'error',
          title: apply ? g.applyFailed : g.saveFailed,
          message: (errors as Record<string, string>)[sshError] || g.sshErrUnknown
        })
      } else {
        notifyError(err, apply ? g.applyFailed : g.saveFailed)
      }
    } finally {
      if (seq === saveSeq.current) {
        setSaving(false)
      }
    }
  }

  // OAuth sign-in: persist the URL + oauth mode first (so the saved config has
  // the URL the login window needs), then open the gateway login window and
  // refresh the connection status from the saved config once it completes.
  const signIn = async () => {
    const seq = ++signingSeq.current

    if (!trimmedUrl) {
      notify({ kind: 'warning', title: g.incompleteTitle, message: g.enterUrlFirst })

      return
    }

    setSigningIn(true)

    try {
      // Save (don't apply/restart) so the login window has a URL to use and the
      // oauth mode is persisted, without yet flipping the live connection.
      const saved = await window.roboDesktop.saveConnectionConfig({
        mode: state.mode,
        profile: scope ?? undefined,
        remoteAuthMode: 'oauth',
        remoteUrl: trimmedUrl
      })

      if (seq !== signingSeq.current) {
        return
      }

      acceptSavedConfig(saved)

      const result = await window.roboDesktop.oauthLoginConnectionConfig(trimmedUrl)

      if (seq !== signingSeq.current) {
        return
      }

      if (result.connected) {
        const refreshed = await window.roboDesktop.getConnectionConfig(scope)
        acceptSavedConfig(refreshed)
        notify({ kind: 'success', title: g.signedIn, message: g.connectedTo(providerLabel) })
      } else {
        notify({
          kind: 'warning',
          title: t.boot.failure.signInIncompleteTitle,
          message: t.boot.failure.signInIncompleteMessage
        })
      }
    } catch (err) {
      if (seq === signingSeq.current) {
        notifyError(err, g.signInFailed)
      }
    } finally {
      if (seq === signingSeq.current) {
        setSigningIn(false)
      }
    }
  }

  const signOut = async () => {
    const seq = ++signingSeq.current
    setSigningIn(true)

    try {
      await window.roboDesktop.oauthLogoutConnectionConfig(trimmedUrl || undefined)
      const refreshed = await window.roboDesktop.getConnectionConfig(scope)

      if (seq !== signingSeq.current) {
        return
      }

      acceptSavedConfig(refreshed)
      notify({ kind: 'success', title: g.signedOutTitle, message: g.signedOutMessage })
    } catch (err) {
      if (seq === signingSeq.current) {
        notifyError(err, g.signOutFailed)
      }
    } finally {
      if (seq === signingSeq.current) {
        setSigningIn(false)
      }
    }
  }

  const resolveSshHost = async (host: string) => {
    if (!host || !window.roboDesktop?.sshResolveHost) {
      return
    }

    const seq = ++sshResolveSeq.current

    try {
      const resolved = await window.roboDesktop.sshResolveHost(host)

      if (seq !== sshResolveSeq.current) {
        return
      }

      setState(current => enrichSelectedSshHost(current, host, resolved))
    } catch {
      return
    }
  }

  const selectHost = (value: string) => {
    if (value === SSH_HOST_CUSTOM) {
      setSshCustomHost(true)
      setState(current => selectSshHost(current, ''))

      return
    }

    setSshCustomHost(false)
    setState(current => selectSshHost(current, value))
    void resolveSshHost(value)
  }

  const testSsh = async () => {
    const seq = ++sshTestSeq.current

    if (!state.sshHost.trim()) {
      notify({ kind: 'warning', title: g.incompleteTitle, message: g.sshIncompleteHost })

      return
    }

    setTesting(true)
    setLastTest(null)

    try {
      const result = await window.roboDesktop.testConnectionConfig(payload())

      if (seq !== sshTestSeq.current) {
        return
      }

      if (!result.reachable) {
        const errors = {
          'auth-failed': g.sshErrAuth,
          'robo-not-found': g.sshErrNotInstalled,
          'host-key-changed': g.sshErrHostKey,
          timeout: g.sshErrTimeout,
          unreachable: g.sshErrUnreachable,
          'unsupported-platform': g.sshErrPlatform,
          'update-required': g.sshErrUpdateRequired,
          unknown: g.sshErrUnknown
        }

        throw new Error(errors[result.sshError || 'unknown'] || result.error || g.sshErrUnknown)
      }

      const message = g.sshReachable(result.host || state.sshHost, result.remotePlatform || '?')
      setLastTest(message)
      notify({ kind: 'success', title: g.reachableTitle, message })
    } catch (err) {
      if (seq === sshTestSeq.current) {
        notifyError(err, g.testFailed)
      }
    } finally {
      if (seq === sshTestSeq.current) {
        setTesting(false)
      }
    }
  }

  const testRemote = async () => {
    const seq = ++sshTestSeq.current

    if (!canUseRemote) {
      notify({
        kind: 'warning',
        title: g.incompleteTitle,
        message: authMode === 'oauth' ? g.incompleteSignInTest : g.incompleteTokenTest
      })

      return
    }

    setTesting(true)
    setLastTest(null)

    try {
      const result = await window.roboDesktop.testConnectionConfig({
        mode: 'remote',
        profile: scope ?? undefined,
        remoteAuthMode: authMode,
        remoteToken: authMode === 'token' ? remoteToken.trim() || undefined : undefined,
        remoteUrl: trimmedUrl
      })

      if (seq !== sshTestSeq.current) {
        return
      }

      const message = g.connectedTo(result.baseUrl || trimmedUrl, result.version ?? undefined)
      setLastTest(message)
      notify({ kind: 'success', title: g.reachableTitle, message })
    } catch (err) {
      if (seq === sshTestSeq.current) {
        notifyError(err, g.testFailed)
      }
    } finally {
      if (seq === sshTestSeq.current) {
        setTesting(false)
      }
    }
  }

  if (loading) {
    return (
      <SettingsSkeleton
        sections={[
          { heading: true, rows: 3 },
          { heading: true, rows: 3 }
        ]}
      />
    )
  }

  if (!window.roboDesktop?.getConnectionConfig) {
    return <EmptyState description={g.unavailableDesc} title={g.unavailableTitle} />
  }

  return (
    <SettingsContent bare={embedded}>
      {embedded ? null : (
        <div className="mb-5">
          <div className="flex items-center gap-2 text-[length:var(--conversation-text-font-size)] font-medium">
            <Globe className="size-4 text-muted-foreground" />
            {g.title}
            {state.envOverride ? <Pill tone="primary">{g.envOverride}</Pill> : null}
          </div>
          <p className="mt-2 max-w-2xl text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)">
            {g.intro}
          </p>
        </div>
      )}

      {namedProfiles.length > 0 ? (
        <div className="mb-5 grid gap-2">
          <div className="text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
            {g.appliesTo}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <ScopeChip active={scope === null} label={g.allProfiles} onSelect={() => setScope(null)} />
            {namedProfiles.map(profile => (
              <ScopeChip
                active={scope === profile.name}
                key={profile.name}
                label={profile.name}
                onSelect={() => setScope(profile.name)}
              />
            ))}
          </div>
          <p className="text-[length:var(--conversation-caption-font-size)] leading-(--conversation-caption-line-height) text-(--ui-text-tertiary)">
            {scope === null ? g.defaultConnection : g.profileConnection(scope)}
          </p>
        </div>
      ) : null}

      {state.envOverride ? (
        <div className="mb-5 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-[length:var(--conversation-caption-font-size)] text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <div>
            <div className="font-medium">{g.envOverrideTitle}</div>
            <div className="mt-1 leading-5">{g.envOverrideDesc}</div>
          </div>
        </div>
      ) : null}

      <div className="mb-5 grid gap-2">
        <div className="text-[length:var(--conversation-caption-font-size)] font-medium text-(--ui-text-secondary)">
          {g.modeTitle}
        </div>
        <div className="grid auto-rows-fr grid-cols-1 gap-2 sm:grid-cols-2 min-[72rem]:grid-cols-4">
          <ModeCard
            active={state.mode === 'local'}
            description={scope === null ? g.localDesc : g.inheritDesc}
            disabled={state.envOverride}
            icon={Monitor}
            onSelect={() => setState(current => ({ ...current, mode: 'local' }))}
            title={scope === null ? g.localTitle : g.inheritTitle}
          />
          <ModeCard
            active={state.mode === 'remote'}
            description={g.remoteDesc}
            disabled={state.envOverride}
            hint={g.remoteAuthHint}
            icon={Globe}
            onSelect={() => setState(current => ({ ...current, mode: 'remote' }))}
            title={g.remoteTitle}
          />
          <ModeCard
            active={state.mode === 'ssh'}
            description={g.sshDesc}
            disabled={state.envOverride}
            hint={g.sshTrustHint}
            icon={Terminal}
            onSelect={() => setState(current => ({ ...current, mode: 'ssh' }))}
            title={g.sshTitle}
          />
        </div>
      </div>

      {state.mode === 'remote' && !state.envOverride ? (
        <div className="mt-5 grid gap-1">
          <ListRow
            action={
              <Input
                className={cn('h-8', CONTROL_TEXT)}
                disabled={state.envOverride}
                onChange={event => setState(current => ({ ...current, remoteUrl: event.target.value }))}
                placeholder="https://gateway.example.com/robo"
                value={state.remoteUrl}
              />
            }
            description={g.remoteUrlDesc}
            title={g.remoteUrlTitle}
          />

          {state.mode === 'remote' && probeStatus === 'probing' ? (
            <div className="flex items-center gap-2 py-3 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
              <Loader2 className="size-4 animate-spin" />
              {g.probing}
            </div>
          ) : null}

          {state.mode === 'remote' && probeStatus === 'error' ? (
            <div className="flex items-start gap-2 py-3 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              {g.probeError}
            </div>
          ) : null}

          {/* OAuth / password gateways: present a sign-in button + connection status. */}
          {state.mode === 'remote' && authResolved && authMode === 'oauth' ? (
            <ListRow
              action={
                oauthConnected ? (
                  <div className="flex items-center gap-2">
                    <Pill tone="primary">
                      <Check className="size-3" /> {g.signedIn}
                    </Pill>
                    <Button disabled={signingIn || state.envOverride} onClick={() => void signOut()} variant="outline">
                      {signingIn ? <Loader2 className="animate-spin" /> : null}
                      {g.signOut}
                    </Button>
                  </div>
                ) : (
                  <Button disabled={signingIn || state.envOverride || !trimmedUrl} onClick={() => void signIn()}>
                    {signingIn ? <Loader2 className="animate-spin" /> : <LogIn />}
                    {isPasswordProvider ? g.signIn : g.signInWith(providerLabel)}
                  </Button>
                )
              }
              description={
                oauthConnected
                  ? isPasswordProvider
                    ? g.authSignedInPassword
                    : g.authSignedInOauth
                  : isPasswordProvider
                    ? g.authNeedsPassword
                    : g.authNeedsOauth(providerLabel)
              }
              title={g.authTitle}
            />
          ) : null}

          {/* Session-token gateways: keep the existing token entry box. */}
          {state.mode === 'remote' && authResolved && authMode === 'token' ? (
            <ListRow
              action={
                <Input
                  autoComplete="off"
                  className={cn('h-8 font-mono', CONTROL_TEXT)}
                  disabled={state.envOverride}
                  onChange={event => setRemoteToken(event.target.value)}
                  placeholder={
                    state.remoteTokenSet
                      ? g.existingToken(state.remoteTokenPreview ?? g.savedToken)
                      : g.pasteSessionToken
                  }
                  type="password"
                  value={remoteToken}
                />
              }
              description={g.tokenDesc}
              title={g.tokenTitle}
            />
          ) : null}
        </div>
      ) : null}

      {state.mode === 'ssh' && !state.envOverride ? (
        <div className="mt-5 grid gap-1">
          {sshHostSuggestions.length > 0 && !sshCustomHost ? (
            <ListRow
              action={
                <Select
                  onValueChange={selectHost}
                  value={sshHostSuggestions.includes(state.sshHost) ? state.sshHost : SSH_HOST_CUSTOM}
                >
                  <SelectTrigger className={cn('h-8', CONTROL_TEXT)}>
                    <SelectValue placeholder={g.sshHostPick} />
                  </SelectTrigger>
                  <SelectContent>
                    {sshHostSuggestions.map(host => (
                      <SelectItem key={host} value={host}>
                        {host}
                      </SelectItem>
                    ))}
                    <SelectItem value={SSH_HOST_CUSTOM}>{g.sshHostCustom}</SelectItem>
                  </SelectContent>
                </Select>
              }
              description={g.sshHostPickDesc}
              title={g.sshHostPickTitle}
            />
          ) : (
            <ListRow
              action={
                <Input
                  autoFocus={sshCustomHost}
                  className={cn('h-8', CONTROL_TEXT)}
                  onBlur={() => {
                    // Empty host on blur with suggestions available = the user backed
                    // out of Custom; return to the dropdown.
                    if (!state.sshHost.trim() && sshHostSuggestions.length > 0) {
                      setSshCustomHost(false)

                      return
                    }

                    void resolveSshHost(state.sshHost)
                  }}
                  onChange={event => setState(current => selectSshHost(current, event.target.value))}
                  value={state.sshHost}
                />
              }
              description={g.sshHostDesc}
              title={g.sshHostTitle}
            />
          )}
          <ListRow
            action={
              <Input
                className={cn('h-8', CONTROL_TEXT)}
                onChange={event => setState(current => ({ ...current, sshUser: event.target.value }))}
                placeholder={g.sshUserPlaceholder}
                value={state.sshUser}
              />
            }
            description={g.sshUserDesc}
            title={g.sshUserTitle}
          />
          <ListRow
            action={
              <Input
                className={cn('h-8', CONTROL_TEXT)}
                inputMode="numeric"
                onChange={event =>
                  setState(current => ({ ...current, sshPort: event.target.value ? Number(event.target.value) : null }))
                }
                placeholder="22"
                value={state.sshPort ?? ''}
              />
            }
            description={g.sshPortDesc}
            title={g.sshPortTitle}
          />
          <ListRow
            action={
              <Input
                className={cn('h-8 font-mono', CONTROL_TEXT)}
                onChange={event => setState(current => ({ ...current, sshKeyPath: event.target.value }))}
                value={state.sshKeyPath}
              />
            }
            description={g.sshKeyDesc}
            title={g.sshKeyTitle}
          />
          <ListRow
            action={
              <Input
                className={cn('h-8 font-mono', CONTROL_TEXT)}
                onChange={event => setState(current => ({ ...current, sshRemoteRoboPath: event.target.value }))}
                placeholder={g.sshRoboPathPlaceholder}
                value={state.sshRemoteRoboPath}
              />
            }
            description={g.sshRoboPathDesc}
            title={g.sshRoboPathTitle}
          />
          {scope !== null ? (
            <ListRow
              action={
                <Input
                  className={cn('h-8 font-mono', CONTROL_TEXT)}
                  onChange={event => setState(current => ({ ...current, sshRemoteProfile: event.target.value }))}
                  placeholder={scope}
                  value={state.sshRemoteProfile}
                />
              }
              description={g.sshRemoteProfileDesc}
              title={g.sshRemoteProfileTitle}
            />
          ) : null}
        </div>
      ) : null}

      {lastTest ? <div className="mt-4 text-xs text-primary">{lastTest}</div> : null}

      <div className="mt-6 flex flex-wrap items-center justify-end gap-4">
        {state.mode === 'remote' ? (
          <Button
            className="mr-auto"
            disabled={state.envOverride || testing || !canUseRemote}
            onClick={() => void testRemote()}
            size="sm"
            variant="text"
          >
            {testing ? <Loader2 className="animate-spin" /> : null}
            {g.testRemote}
          </Button>
        ) : state.mode === 'ssh' ? (
          <Button
            className="mr-auto"
            disabled={testing || !state.sshHost.trim()}
            onClick={() => void testSsh()}
            size="sm"
            variant="text"
          >
            {testing ? <Loader2 className="animate-spin" /> : null}
            {g.sshTestConnection}
          </Button>
        ) : null}
        {embedded ? null : (
          <Button
            disabled={state.envOverride || saving}
            onClick={() => void save(false)}
            size="sm"
            variant="textStrong"
          >
            {g.saveForRestart}
          </Button>
        )}
        <Button disabled={state.envOverride || saving} onClick={() => void save(true)} size="sm">
          {saving ? <Loader2 className="animate-spin" /> : null}
          {g.saveAndReconnect}
        </Button>
      </div>

      {embedded ? null : (
        <div className="mt-6 grid gap-1">
          <ListRow
            action={
              <Button onClick={() => void window.roboDesktop?.revealLogs()} size="sm" variant="textStrong">
                <FileText />
                {g.openLogs}
              </Button>
            }
            description={g.diagnosticsDesc}
            title={g.diagnostics}
          />
        </div>
      )}
    </SettingsContent>
  )
}
