import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { useI18n } from '@/i18n'

interface BusySendChoiceProps {
  onKeep: () => void
  onQueue: () => void
  onSendNow: () => void
}

/**
 * The choice shown above the composer when Enter is pressed on a message while
 * Robo is still working: send it now (stop the current step, Robo reads this
 * first) or queue it for after. Esc keeps the words in the composer. Rendered
 * inside the status stack's card, above the queue, so it sits exactly where
 * the queued message would otherwise have silently gone.
 */
export function BusySendChoice({ onKeep, onQueue, onSendNow }: BusySendChoiceProps) {
  const { t } = useI18n()
  const c = t.composer

  return (
    <div aria-label={c.busyChoiceTitle} className="px-2 py-1.5" data-slot="busy-send-choice" role="group">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground/92">
        <Codicon className="shrink-0 text-muted-foreground/70" name="clock" size="0.8rem" />
        <span className="truncate">{c.busyChoiceTitle}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button className="h-6 px-2.5 text-xs" onClick={onSendNow} size="xs" type="button">
          {c.busyChoiceSendNow}
          <span className="text-[0.625rem] opacity-60">⏎</span>
        </Button>
        <span className="text-[0.68rem] text-muted-foreground/75">{c.busyChoiceSendNowHint}</span>
        <Button className="h-6 px-2.5 text-xs" onClick={onQueue} size="xs" type="button" variant="secondary">
          {c.busyChoiceQueue}
        </Button>
        <span className="text-[0.68rem] text-muted-foreground/75">{c.busyChoiceQueueHint}</span>
        <Button className="ml-auto" onClick={onKeep} size="micro" type="button" variant="text">
          {c.busyChoiceKeep}
        </Button>
      </div>
    </div>
  )
}
