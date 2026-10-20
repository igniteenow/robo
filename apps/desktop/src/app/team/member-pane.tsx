/**
 * One seat of the team: a role strip (Lead / Reviewer N / Final outcome,
 * status, the model it runs on) over a LIVE, read-only view of that member's
 * session — the same transcript the primary chat renders, minus the composer.
 * One composer on the page talks to whichever seat is selected, so the panes
 * never carry the docked/floating composer that would collide in a grid.
 * Clicking a pane selects it. Before the team starts, the seat only shows its
 * model pick. The Final seat (`TEAM_FINAL_INDEX`) is the same pane with a
 * star header, no model pick of its own (it follows the lead), and its own
 * waiting copy: it fills in when the run ends and stays open to questions.
 */

import { useStore } from '@nanostores/react'
import { computed } from 'nanostores'
import { useMemo } from 'react'

import { buildTileView, TileChat } from '@/app/chat/session-tile'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { TEAM_FINAL_INDEX } from '@/lib/team/protocol'
import { useStoreSelector } from '@/lib/use-session-slice'
import { cn } from '@/lib/utils'
import { $sessionStates } from '@/store/session-states'
import { $teamMembers, type TeamMember, type TeamMemberConfig, type TeamMemberStatus } from '@/store/team'

interface MemberPaneProps {
  index: number
  config: TeamMemberConfig
  member?: TeamMember
  /** The run is live: model picks are frozen (they apply to the next team). */
  locked: boolean
  /** This seat is the single composer's current target. */
  selected: boolean
  onSelect: (index: number) => void
  onPickModel: (index: number) => void
}

/** What the badge says: the controller's status, or "needs you" while the
 *  session is blocked on the user (an approval, a question). */
type SeatStatus = 'needsInput' | TeamMemberStatus

const STATUS_ICON: Record<SeatStatus, string> = {
  creating: 'loading',
  error: 'warning',
  idle: 'circle-outline',
  needsInput: 'question',
  reviewing: 'checklist',
  sideTask: 'tools',
  synthesizing: 'loading',
  working: 'loading'
}

const STATUS_TONE: Record<SeatStatus, 'default' | 'destructive' | 'muted' | 'warn'> = {
  creating: 'muted',
  error: 'destructive',
  idle: 'muted',
  needsInput: 'warn',
  reviewing: 'default',
  sideTask: 'warn',
  synthesizing: 'default',
  working: 'default'
}

/** Statuses whose icon is the spinner. */
const SPINNING: ReadonlySet<SeatStatus> = new Set<SeatStatus>(['creating', 'reviewing', 'sideTask', 'synthesizing', 'working'])

function MemberChat({ index, storedSessionId }: { index: number; storedSessionId: string }) {
  // The member's runtime id lives in `$teamMembers`; the view reads the
  // session's own `$sessionStates` slice through it, exactly like a tile.
  const view = useMemo(
    () =>
      buildTileView(
        storedSessionId,
        computed($teamMembers, members => members.find(m => m.index === index)?.runtimeId ?? null)
      ),
    [index, storedSessionId]
  )

  const runtimeId = useStore(view.$runtimeId)

  if (!runtimeId) {
    return null
  }

  return <TileChat hideComposer runtimeId={runtimeId} storedSessionId={storedSessionId} view={view} />
}

export function MemberPane({ config, index, locked, member, onPickModel, onSelect, selected }: MemberPaneProps) {
  const { t } = useI18n()
  const copy = t.team
  const runtimeId = member?.runtimeId ?? null
  // `$sessionStates` republishes per delta; the selectors each return one
  // scalar, so the pane re-renders only on the edges it shows — not per token.
  const needsInput = useStoreSelector($sessionStates, states => Boolean(runtimeId && states[runtimeId]?.needsInput))

  const started = useStoreSelector($sessionStates, states =>
    Boolean(runtimeId && (states[runtimeId]?.messages.length ?? 0) > 0)
  )

  const sessionBusy = useStoreSelector($sessionStates, states => Boolean(runtimeId && states[runtimeId]?.busy))

  // The controller's status is the run's view of the seat. A seat the user is
  // talking to directly (a question to the Final, a nudge to a member) is
  // busy without the controller knowing, so the session's own busy flag
  // promotes an idle seat to Working — the send is visibly received.
  const controllerStatus = member?.status ?? 'idle'

  const status: SeatStatus = needsInput
    ? 'needsInput'
    : sessionBusy && controllerStatus === 'idle'
      ? 'working'
      : controllerStatus

  const isFinal = index === TEAM_FINAL_INDEX
  const name = isFinal ? copy.final : index === 0 ? copy.lead : copy.reviewer(index + 1)
  const modelLabel = config.model || copy.modelMissing
  const spinning = SPINNING.has(status)
  const bound = Boolean(member?.storedSessionId && member.runtimeId)
  // What an idle seat with nothing to show yet says: the Final waits for the
  // run to end, the lead opens on Start, a reviewer waits for the lead.
  const waitingCopy = isFinal ? copy.waitingForFinal : index === 0 ? copy.seatEmpty : copy.waitingForLead

  // A plain div, not a button: the pane contains the model button and the
  // transcript's own controls, and nesting interactive elements is invalid.
  // A click anywhere selects the pane for the shared composer.
  return (
    <div
      className={cn(
        'flex min-h-0 min-w-0 flex-col rounded-lg bg-(--ui-chat-surface-background)',
        'ring-1 transition-[box-shadow,border-color]',
        selected ? 'ring-2 ring-primary' : 'ring-(--ui-stroke-secondary)/55'
      )}
      data-member-index={index}
      data-member-selected={selected || undefined}
      data-member-status={status}
      data-slot={isFinal ? 'team-final' : 'team-member'}
      onClick={() => onSelect(index)}
    >
      <div
        className={cn(
          'flex shrink-0 items-center gap-2 border-b border-(--ui-stroke-secondary)/55 px-3 py-1.5 text-xs',
          isFinal && 'bg-primary/5'
        )}
      >
        <Codicon
          className={cn('shrink-0', index === 0 || isFinal ? 'text-primary' : 'text-muted-foreground')}
          name={isFinal ? 'star-full' : index === 0 ? 'hubot' : 'account'}
          size="0.85rem"
        />
        <span className="truncate font-medium">{name}</span>
        <Badge size="xs" variant={STATUS_TONE[status]}>
          <Codicon name={STATUS_ICON[status]} size="0.6rem" spinning={spinning && STATUS_ICON[status] === 'loading'} />
          {copy.status[status]}
        </Badge>
        {isFinal ? (
          // The Final follows the lead's pick; it has no pick of its own.
          <span className="ml-auto truncate text-[0.6875rem] text-muted-foreground">{copy.finalModelHint}</span>
        ) : (
          <Tip label={locked ? undefined : copy.changeModel}>
            <span className="ml-auto max-w-[55%]">
              <Button
                className="w-full font-mono text-[0.6875rem]"
                disabled={locked}
                onClick={() => onPickModel(index)}
                size="xs"
                type="button"
                variant="outline"
              >
                <span className="truncate">{modelLabel}</span>
                {config.provider ? <span className="truncate opacity-60">· {config.provider}</span> : null}
                {locked ? null : <Codicon name="chevron-down" size="0.6rem" />}
              </Button>
            </span>
          </Tip>
        )}
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-b-lg">
        {bound ? (
          <>
            <MemberChat index={index} storedSessionId={member!.storedSessionId!} />
            {/* A bound seat that hasn't been asked anything yet shows a quiet
                waiting note instead of an empty transcript. */}
            {!started && status === 'idle' ? (
              <div className="pointer-events-none absolute inset-0 grid place-items-center p-4 text-center text-xs text-muted-foreground">
                {waitingCopy}
              </div>
            ) : null}
          </>
        ) : (
          <div className="grid h-full place-items-center p-4 text-center text-xs text-muted-foreground">
            <div className="max-w-[18rem] space-y-1">
              {status === 'error' ? (
                <>
                  <div className="text-(--ui-danger,#f87171)">{copy.seatError}</div>
                  {member?.error ? <div className="break-words opacity-80">{member.error}</div> : null}
                </>
              ) : status === 'creating' ? (
                <div className="flex items-center justify-center gap-1.5">
                  <Codicon name="loading" size="0.75rem" spinning />
                  {copy.seatCreating}
                </div>
              ) : (
                <div>{isFinal ? copy.waitingForFinal : copy.seatEmpty}</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
