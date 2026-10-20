'use client'

import { useStore } from '@nanostores/react'
import { type FC, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useSessionView } from '@/app/chat/session-view'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useI18n } from '@/i18n'
import { triggerHaptic } from '@/lib/haptics'
import { AlertCircle, ChevronDown, Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $gateway } from '@/store/gateway'
import { notifyError } from '@/store/notifications'
import {
  type ApprovalRequest,
  clearApprovalRequest,
  registerApprovalInlineAnchor,
  sessionApprovalInlineVisible,
  sessionApprovalRequest
} from '@/store/prompts'

import type { ToolPart } from './fallback-model'

// Inline approval control. Rendered as a compact button strip
// under the pending tool row that raised the approval (the row already shows
// the command, so the strip deliberately doesn't repeat it) instead of as a
// modal overlay.
//
// Binding is POSITIONAL, not command-matched: the desktop `tool.start` payload
// carries no structured args (only tool_id/name/context — see
// tui_gateway/server.py::_on_tool_start), so we cannot join the approval to the
// row by command string. But `approval.request` only ever fires from the
// `terminal` / `execute_code` guards and the agent thread blocks on exactly one
// approval at a time, so the single pending row of those tools IS the row that
// raised it. The command/description text comes from `$approvalRequest` (the
// event payload), which is the only place that data reliably exists.
export const APPROVAL_TOOLS = new Set(['terminal', 'execute_code'])

// Canonical gateway choices (ui-tui/src/components/prompts.tsx).
type ApprovalChoice = 'once' | 'session' | 'always' | 'deny'

export const PendingToolApproval: FC<{ part: ToolPart }> = ({ part }) => {
  // The tool row lives in whichever session's transcript rendered it — read
  // THAT session's approval (works for the primary and every tile).
  const sessionId = useStore(useSessionView().$runtimeId)
  const $request = useMemo(() => sessionApprovalRequest(sessionId), [sessionId])
  const request = useStore($request)

  if (!request || !APPROVAL_TOOLS.has(part.toolName)) {
    return null
  }

  return <InlineApprovalBar request={request} />
}

const InlineApprovalBar: FC<{ request: ApprovalRequest }> = ({ request }) => {
  useEffect(() => registerApprovalInlineAnchor(request.sessionId), [request.sessionId])

  return <ApprovalBar request={request} surface="inline" />
}

export const PendingApprovalFallback: FC = () => {
  const { t } = useI18n()
  const sessionId = useStore(useSessionView().$runtimeId)
  const $request = useMemo(() => sessionApprovalRequest(sessionId), [sessionId])
  const $inlineVisible = useMemo(() => sessionApprovalInlineVisible(sessionId), [sessionId])
  const request = useStore($request)
  const inlineVisible = useStore($inlineVisible)

  if (!request || inlineVisible) {
    return null
  }

  // The card is anchored to the bottom of its chat surface and grows UPWARD
  // when Details opens. The surface is overflow-hidden, so without a height
  // bound a short surface — a team seat in a 2×2 grid, a small window — pushed
  // the header and the Apply / Keep buttons past the top edge, clipped, with
  // the wheel reaching only the transcript underneath: no way to answer.
  // Bound it to the surface, let the details shrink and scroll first (the
  // buttons stay in view), and let the card itself scroll as the last resort.
  // (The transcript is a sibling, not an ancestor, so a wheel over the card
  // never chains into it; the clipped region was what let it through.)
  return (
    <div
      className="pointer-events-none absolute left-1/2 z-30 flex max-h-[calc(100%-var(--composer-measured-height)-1.625rem)] w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 flex-col"
      data-slot="tool-approval-fallback"
      style={{ bottom: 'calc(var(--composer-measured-height) + 0.875rem)' }}
    >
      <div
        className="pointer-events-auto flex min-h-0 flex-col overflow-y-auto rounded-xl border border-primary/30 bg-(--ui-chat-surface-background) px-3 py-2 shadow-lg backdrop-blur-xl [-webkit-backdrop-filter:blur(1rem)]"
        data-slot="tool-approval-card"
      >
        <div className="flex min-w-0 shrink-0 items-center gap-2 text-sm text-primary">
          <AlertCircle className="size-4 shrink-0" />
          <span className="shrink-0 font-medium">
            {request.kind === 'correction' ? t.assistant.approval.correctionNeeded : t.assistant.approval.jumpToApproval}
          </span>
          {request.description && (
            <span className="min-w-0 truncate text-(--ui-text-tertiary)">{request.description}</span>
          )}
        </div>
        <ApprovalBar request={request} surface="floating" />
      </div>
    </div>
  )
}

const isMac = typeof navigator !== 'undefined' && /Mac|iP(hone|ad|od)/.test(navigator.platform)

// Sessions with an approval bar on screen (inline and floating count once per
// session). ⌘⏎ / Esc are window-level shortcuts; with several sessions
// holding approvals at once — team seats running commands side by side,
// tiles — one keystroke must not answer them all, including a command in a
// pane the user never looked at.
const mountedApprovalSessions = new Map<string, number>()

function trackMountedApproval(sessionId: string | null): () => void {
  const key = sessionId ?? ''
  mountedApprovalSessions.set(key, (mountedApprovalSessions.get(key) ?? 0) + 1)

  return () => {
    const next = (mountedApprovalSessions.get(key) ?? 1) - 1

    if (next > 0) {
      mountedApprovalSessions.set(key, next)
    } else {
      mountedApprovalSessions.delete(key)
    }
  }
}

/** Whether this bar answers a keyboard shortcut: always while it is the only
 *  approval on screen (the primary chat's long-standing behaviour); otherwise
 *  only when the focus sits inside its own chat surface, so the keystroke
 *  reaches exactly the approval the user is looking at. */
function ownsShortcut(bar: HTMLElement | null): boolean {
  const surface = bar?.closest('[data-chat-surface]') ?? null
  const active = typeof document === 'undefined' ? null : document.activeElement

  if (surface && active && surface.contains(active)) {
    return true
  }

  return mountedApprovalSessions.size <= 1
}

const ApprovalBar: FC<{ request: ApprovalRequest; surface: 'floating' | 'inline' }> = ({ request, surface }) => {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const { t } = useI18n()
  const copy = t.assistant.approval
  const gateway = useStore($gateway)
  const [submitting, setSubmitting] = useState<ApprovalChoice | null>(null)
  // "Always allow" persists the pattern to ~/.robo/config.yaml permanently, so
  // it goes through a confirm step rather than firing straight from the menu.
  const [confirmAlways, setConfirmAlways] = useState(false)
  // The pending tool row only shows a single truncated line of the command, and
  // a pending row can't be expanded (no result yet), so the full command was
  // previously only reachable via the "Always allow" modal. Let the user reveal
  // it inline instead — "expand, Run" (2 clicks) rather than the modal dance.
  const [showCommand, setShowCommand] = useState(false)
  const busy = submitting !== null
  // false when the backend won't honor a permanent allow (tirith warning) → hide "Always allow".
  const allowPermanent = request.allowPermanent !== false
  const choices = request.choices ?? (request.smartDenied ? ['once', 'deny'] : undefined)
  const allowSession = choices ? choices.includes('session') : true
  const allowAlways = choices ? choices.includes('always') : allowPermanent
  const hasMoreOptions = allowSession || allowAlways
  const hasCommand = request.command.trim().length > 0
  // A fact-check correction uses the same bar with its own words: "Apply"
  // instead of "Run", "Keep answer" instead of "Reject", "Details" for the
  // proposed change instead of "Command".
  const correction = request.kind === 'correction'
  const primaryLabel = correction ? copy.apply : copy.run
  const sessionLabel = correction ? copy.applySession : copy.allowSession
  const denyLabel = correction ? copy.keep : copy.reject
  const detailsLabel = correction ? copy.details : copy.command

  const respond = useCallback(
    async (choice: ApprovalChoice) => {
      // Another bar (or the keyboard path) may have already resolved this
      // approval; the map is the single source of truth, so bail if this
      // session's request is gone.
      if (busy || !sessionApprovalRequest(request.sessionId).get()) {
        return
      }

      if (!gateway) {
        notifyError(new Error(copy.gatewayDisconnected), copy.sendFailed)

        return
      }

      setSubmitting(choice)

      try {
        await gateway.request<{ resolved?: boolean }>('approval.respond', {
          choice,
          session_id: request.sessionId ?? undefined
        })
        triggerHaptic(choice === 'deny' ? 'cancel' : 'submit')
        clearApprovalRequest(request.sessionId)
      } catch (error) {
        notifyError(error, copy.sendFailed)
        setSubmitting(null)
      }
    },
    [busy, copy.gatewayDisconnected, copy.sendFailed, gateway, request.sessionId]
  )

  useEffect(() => trackMountedApproval(request.sessionId), [request.sessionId])

  // ⌘/Ctrl+Enter → Run, Esc → Reject — for THIS approval only when several
  // are on screen (see ownsShortcut).
  // While the confirm dialog is open it owns the keyboard (Esc closes it), so
  // the strip-level shortcuts stand down to avoid denying the whole approval.
  useEffect(() => {
    if (confirmAlways) {
      return
    }

    const onKeyDown = (event: KeyboardEvent) => {
      const choice: ApprovalChoice | null =
        event.key === 'Enter' && (event.metaKey || event.ctrlKey) ? 'once' : event.key === 'Escape' ? 'deny' : null

      if (!choice || !ownsShortcut(rootRef.current)) {
        return
      }

      event.preventDefault()
      void respond(choice)
    }

    window.addEventListener('keydown', onKeyDown, true)

    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [confirmAlways, respond])

  // Floating: a flex column so the details block can shrink inside the card's
  // height bound while the action row keeps its size.
  return (
    <div
      className={cn(surface === 'inline' ? 'mt-1 ps-5' : 'mt-2 flex min-h-0 flex-col')}
      data-slot={surface === 'inline' ? 'tool-approval-inline' : 'tool-approval-actions'}
      ref={rootRef}
    >
      <div className="flex shrink-0 items-center gap-2.5">
        <div className="inline-flex h-6 items-stretch overflow-hidden rounded-md border border-primary/25 bg-primary/10 text-primary">
          <Button
            className="h-full gap-1 rounded-none px-2 text-xs font-medium text-primary hover:bg-primary/15 hover:text-primary"
            disabled={busy}
            onClick={() => void respond('once')}
            size="xs"
            variant="ghost"
          >
            {submitting === 'once' ? <Loader2 className="size-3 animate-spin" /> : primaryLabel}
            {submitting !== 'once' && <span className="text-[0.625rem] text-primary/60">{isMac ? '⌘⏎' : 'Ctrl⏎'}</span>}
          </Button>
          {hasMoreOptions && <span aria-hidden className="w-px self-stretch bg-primary/20" />}
          {hasMoreOptions && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  aria-label={copy.moreOptions}
                  className="h-full w-5 rounded-none px-0 text-primary hover:bg-primary/15 hover:text-primary"
                  disabled={busy}
                  size="xs"
                  variant="ghost"
                >
                  <ChevronDown className="size-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-44">
                {allowSession && (
                  <DropdownMenuItem onSelect={() => void respond('session')}>{sessionLabel}</DropdownMenuItem>
                )}
                {allowAlways && (
                  <DropdownMenuItem
                    onSelect={() => {
                      // Defer one tick so the menu fully unmounts before the dialog
                      // mounts — otherwise Radix's focus-return races the dialog and
                      // dismisses it via onInteractOutside.
                      setTimeout(() => setConfirmAlways(true), 0)
                    }}
                  >
                    {copy.alwaysAllowMenu}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => void respond('deny')} variant="destructive">
                  {denyLabel}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <Button
          className="h-6 gap-1.5 rounded-md px-1.5 text-xs font-normal text-(--ui-text-tertiary) hover:text-foreground"
          disabled={busy}
          onClick={() => void respond('deny')}
          size="xs"
          variant="ghost"
        >
          {submitting === 'deny' ? <Loader2 className="size-3 animate-spin" /> : denyLabel}
          {submitting !== 'deny' && <span className="text-[0.625rem] opacity-55">Esc</span>}
        </Button>

        {hasCommand && (
          <Button
            aria-expanded={showCommand}
            className="h-6 gap-1 rounded-md px-1.5 text-xs font-normal text-(--ui-text-tertiary) hover:text-foreground"
            onClick={() => setShowCommand(value => !value)}
            size="xs"
            variant="ghost"
          >
            {detailsLabel}
            <ChevronDown className={cn('size-3 transition-transform', showCommand && 'rotate-180')} />
          </Button>
        )}
      </div>

      {/* min-h-0 lets the block give up height to the floating card's surface
          bound, scrolling inside itself, so the action row above never has to
          move. (A no-op on the inline surface, which is in normal flow.) */}
      {showCommand && hasCommand && (
        <pre
          className="mt-1.5 max-h-40 min-h-0 shrink overflow-auto whitespace-pre-wrap break-words rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-chat-surface-background) px-2.5 py-1.5 font-mono text-xs leading-snug text-foreground"
          data-slot="tool-approval-details"
        >
          {request.command.trim()}
        </pre>
      )}

      <Dialog onOpenChange={setConfirmAlways} open={confirmAlways}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{copy.alwaysTitle}</DialogTitle>
            <DialogDescription>{copy.alwaysDescription(request.description)}</DialogDescription>
          </DialogHeader>

          {request.command.trim() && (
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md border border-(--ui-stroke-tertiary) bg-(--ui-chat-surface-background) px-2.5 py-1.5 font-mono text-xs leading-snug text-foreground">
              {request.command.trim()}
            </pre>
          )}

          <DialogFooter>
            <Button onClick={() => setConfirmAlways(false)} size="sm" variant="ghost">
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => {
                setConfirmAlways(false)
                void respond('always')
              }}
              size="sm"
              variant="destructive"
            >
              {copy.alwaysAllow}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
