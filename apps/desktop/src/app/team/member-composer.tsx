/**
 * ONE composer for the whole team. The member panes are read-only (their own
 * composers would collide in a grid), so this single bar talks to whichever
 * seat is selected — click a pane, or a chip here, to retarget it. The Final
 * seat is a target like any other, so the outcome can be questioned directly.
 * A message is a queued submit to that seat's session: it never redirects a
 * turn the member is already running (the controller's, or the user's own).
 * Pure over an injected `onSend` and a list of targets, so the page wires the
 * delegate and the names and this stays testable.
 */

import { type KeyboardEvent, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

export interface ComposerTarget {
  /** The seat's member index (`TEAM_FINAL_INDEX` for the Final). */
  index: number
  /** Localized seat name, shown on the chip and in the placeholder. */
  name: string
  /** `null` when the seat has no live session (the composer is disabled). */
  runtimeId: null | string
}

interface MemberComposerProps {
  targets: ComposerTarget[]
  selectedIndex: number
  onSelectIndex: (index: number) => void
  onSend: (index: number, text: string) => Promise<void> | void
  /** The gateway is open. */
  connected: boolean
  /** Why the selected seat cannot be messaged right now (it is still opening,
   *  it could not open, the Final has not been written yet); the generic
   *  "start the team" line when absent. */
  disabledHint?: string
}

export function MemberComposer({
  connected,
  disabledHint,
  onSelectIndex,
  onSend,
  selectedIndex,
  targets
}: MemberComposerProps) {
  const { t } = useI18n()
  const copy = t.team
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)

  const selected = targets.find(target => target.index === selectedIndex)
  const targetName = selected?.name ?? ''
  const bound = Boolean(selected?.runtimeId)
  const canSend = connected && bound && text.trim().length > 0 && !sending

  const send = async () => {
    if (!canSend) {
      return
    }

    const body = text.trim()
    setSending(true)

    try {
      await onSend(selectedIndex, body)
      // Clear only on success; a failed send keeps the text for a retry (the
      // page surfaces the error).
      setText('')
    } catch {
      // Swallowed here — onSend reports the failure.
    } finally {
      setSending(false)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void send()
    }
  }

  return (
    <div className="shrink-0 border-t border-(--ui-stroke-secondary)/55 px-3 py-2" data-slot="team-composer">
      <div className="mb-1 flex items-center gap-1 text-[0.6875rem] text-muted-foreground">
        <span className="shrink-0">{copy.composerTo}</span>
        <div className="flex min-w-0 flex-wrap gap-1">
          {targets.map(target => (
            <button
              aria-pressed={target.index === selectedIndex}
              className={cn(
                'rounded-full px-2 py-0.5 text-[0.6875rem] transition-colors',
                target.index === selectedIndex
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:bg-(--chrome-action-hover)'
              )}
              key={target.index}
              onClick={() => onSelectIndex(target.index)}
              type="button"
            >
              {target.name}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-end gap-2">
        <Textarea
          aria-label={copy.composerLabel}
          className="min-h-9 flex-1 resize-none"
          data-slot="team-composer-input"
          disabled={!connected || !bound}
          onChange={event => setText(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={bound ? copy.composerPlaceholder(targetName) : (disabledHint ?? copy.composerDisabled)}
          rows={1}
          value={text}
        />
        <Button disabled={!canSend} onClick={() => void send()} size="sm" type="button">
          <Codicon name="send" size="0.75rem" />
          {copy.composerSend}
        </Button>
      </div>
    </div>
  )
}
