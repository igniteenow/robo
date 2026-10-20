/**
 * TEAM — the `/team` page: a goal, 2–4 seats each on its own model, Start,
 * the live panes of every member side by side, the Final-outcome pane under
 * them (full width — it reads the whole run and writes the answer, and you
 * can question it), one composer for all of them, and the round/vote log.
 * Opt-in by construction: nothing here mounts until the user opens the page,
 * and the ordinary chat is untouched (members are plain backend sessions).
 */

import { useStore } from '@nanostores/react'
import { type CSSProperties, type KeyboardEvent, useEffect, useState } from 'react'

import { ModelPickerDialog } from '@/components/model-picker'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'
import { clampTeamSize, TEAM_FINAL_INDEX, TEAM_MAX_MEMBERS, TEAM_MIN_MEMBERS, TEAM_UNLIMITED_ROUNDS } from '@/lib/team/protocol'
import { cn } from '@/lib/utils'
import { $gateway } from '@/store/gateway'
import { notifyError } from '@/store/notifications'
import { $activeGatewayProfile } from '@/store/profile'
import { $gatewayState } from '@/store/session'
import {
  $teamConfig,
  $teamLogOpen,
  $teamMembers,
  $teamRun,
  setTeamLogOpen,
  setTeamMaxRounds,
  setTeamMemberModel,
  setTeamSize,
  type TeamRun,
  teamRunActive
} from '@/store/team'

import { resetTeam, startTeamRun, stopTeamRun, submitTeamPrompt } from './controller'
import { type ComposerTarget, MemberComposer } from './member-composer'
import { MemberPane } from './member-pane'
import { TeamRunLog } from './run-log'

/** The Final seat has no model pick of its own (it follows the lead). */
const noPick = () => undefined

const SIZE_OPTIONS = Array.from({ length: TEAM_MAX_MEMBERS - TEAM_MIN_MEMBERS + 1 }, (_, i) => {
  const id = String(TEAM_MIN_MEMBERS + i)

  return { id, label: id }
})

/** The round-cap picks: no cap (the default) and a few sensible caps. A cap
 *  saved by an earlier version (any 1–12) is kept in the list so the control
 *  still shows it. */
const ROUND_PICKS = [TEAM_UNLIMITED_ROUNDS, 3, 6, 9, 12, 20, 30, 50]

function roundOptions(current: number): string[] {
  return (ROUND_PICKS.includes(current) ? ROUND_PICKS : [...ROUND_PICKS, current].sort((a, b) => a - b)).map(String)
}

function runStatusText(run: null | TeamRun, copy: ReturnType<typeof useI18n>['t']['team']): string {
  if (!run) {
    return ''
  }

  switch (run.status) {
    case 'starting':
      return copy.run.starting

    case 'running':
      return copy.run.running(run.round, run.maxRounds)

    case 'stopping':
      return copy.run.stopping

    case 'done':
      return copy.run.done

    case 'failed':
      return copy.run.failed

    case 'stopped':
      return copy.run.stopped

    default:
      return ''
  }
}

/** Grid shape per seat count, so every pane is a full-height, equal cell:
 *  2 → two columns; 3 → three columns; 4 → a 2×2 grid. Each cell owns its
 *  height (`minmax(0,1fr)`) so a long transcript scrolls inside the pane
 *  instead of stretching the grid. */
function gridStyle(size: number): CSSProperties {
  if (size <= 2) {
    return { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gridTemplateRows: 'minmax(0, 1fr)' }
  }

  if (size === 3) {
    return { gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gridTemplateRows: 'minmax(0, 1fr)' }
  }

  return { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gridTemplateRows: 'repeat(2, minmax(0, 1fr))' }
}

export function TeamPage() {
  const { t } = useI18n()
  const copy = t.team
  const config = useStore($teamConfig)
  const members = useStore($teamMembers)
  const run = useStore($teamRun)
  const logOpen = useStore($teamLogOpen)
  const gatewayOpen = useStore($gatewayState) === 'open'
  const gateway = useStore($gateway)
  const profile = useStore($activeGatewayProfile)
  const [goal, setGoal] = useState('')
  const [picking, setPicking] = useState<null | number>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  // Which seat the single composer talks to (default the lead). Kept in range
  // as the member count changes.
  const [selectedMember, setSelectedMember] = useState(0)

  const size = clampTeamSize(config.size)
  const active = teamRunActive(run)
  const canStart = gatewayOpen && !active && goal.trim().length > 0
  const seats = Array.from({ length: size }, (_, index) => index)
  const pickingConfig = picking === null ? null : config.members[picking]
  const finalMember = members.find(m => m.index === TEAM_FINAL_INDEX)

  const seatName = (index: number) =>
    index === TEAM_FINAL_INDEX ? copy.final : index === 0 ? copy.lead : copy.reviewer(index + 1)

  // Who the composer can talk to: every live working seat, then the Final.
  const targets: ComposerTarget[] = [
    ...members.filter(m => m.index < size && m.runtimeId),
    ...(finalMember?.runtimeId ? [finalMember] : [])
  ].map(m => ({ index: m.index, name: seatName(m.index), runtimeId: m.runtimeId }))

  const finalReady = run?.status === 'done' && Boolean(finalMember?.runtimeId)

  // The composer's placeholder when the selected seat has no live session:
  // say why, rather than "start the team" while the team is plainly running.
  const selectedSeat = members.find(m => m.index === selectedMember)

  const composerHint =
    selectedMember === TEAM_FINAL_INDEX && !finalMember?.runtimeId
      ? copy.waitingForFinal
      : selectedSeat?.status === 'error'
        ? copy.seatError
        : active
          ? copy.seatCreating
          : undefined

  useEffect(() => {
    if (selectedMember !== TEAM_FINAL_INDEX && selectedMember >= size) {
      setSelectedMember(0)
    }
  }, [selectedMember, size])

  const sendToMember = async (index: number, text: string) => {
    const runtimeId = members.find(m => m.index === index)?.runtimeId

    if (!runtimeId) {
      return
    }

    try {
      // The same path the controller's briefs take: the message is painted
      // in the seat's pane at once (with the thinking indicator when the seat
      // was idle), and a running turn is never redirected — the text waits
      // for the next one.
      await submitTeamPrompt(runtimeId, text)
    } catch (error) {
      notifyError(error, copy.sendFailed)
      // Rethrow so the composer keeps the text for a retry.
      throw error
    }
  }

  const start = () => {
    if (!canStart) {
      return
    }

    // Like a chat composer: the box clears the moment the goal is sent, so
    // the next goal can be typed; the running goal stays in view in the
    // status line and at the top of the log. A start that never became a run
    // (a seat could not open) hands the text back rather than losing it.
    const text = goal
    setGoal('')

    const handBack = () => setGoal(current => (current.trim() ? current : text))

    void startTeamRun(text).then(
      started => {
        if (!started) {
          handBack()
        }
      },
      error => {
        // startTeamRun reports failures through the run itself; should it
        // ever reject, the goal must not vanish with it.
        notifyError(error, copy.errors.runFailed)
        handBack()
      }
    )
  }

  const onGoalKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      start()
    }
  }

  return (
    <section
      className="flex h-full min-w-0 flex-col overflow-hidden bg-(--ui-chat-surface-background)"
      data-slot="team-page"
    >
      <header className="shrink-0 px-4 pb-2 pt-[calc(var(--titlebar-height)+0.5rem)]">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex min-w-0 items-center gap-2">
            <Codicon className="text-primary" name="organization" size="1rem" />
            <h1 className="m-0 text-sm font-medium">{copy.title}</h1>
            <span className="hidden truncate text-xs text-muted-foreground lg:inline">{copy.subtitle}</span>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <span>{copy.members}</span>
              <SegmentedControl
                disabled={active}
                onChange={id => setTeamSize(Number(id))}
                options={SIZE_OPTIONS}
                value={String(size)}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span>{copy.rounds}</span>
              <Tip label={copy.roundsHint(config.maxRounds)}>
                <span>
                  <Select
                    disabled={active}
                    onValueChange={value => setTeamMaxRounds(Number(value))}
                    value={String(config.maxRounds)}
                  >
                    <SelectTrigger aria-label={copy.rounds} className="w-24" size="xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {roundOptions(config.maxRounds).map(value => (
                        <SelectItem key={value} value={value}>
                          {value === String(TEAM_UNLIMITED_ROUNDS) ? copy.roundsUnlimited : value}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </span>
              </Tip>
            </div>
            <Button onClick={() => setTeamLogOpen(!logOpen)} size="xs" type="button" variant="ghost">
              <Codicon name="checklist" size="0.75rem" />
              {logOpen ? copy.hideLog : copy.showLog}
            </Button>
            <Button
              disabled={members.length === 0 && !run}
              onClick={() => setConfirmReset(true)}
              size="xs"
              type="button"
              variant="ghost"
            >
              <Codicon name="refresh" size="0.75rem" />
              {copy.reset}
            </Button>
          </div>
        </div>

        <div className="mt-2 flex items-end gap-2">
          <Textarea
            aria-label={copy.goalLabel}
            className="min-h-10 flex-1 resize-none"
            data-slot="team-goal"
            disabled={active}
            onChange={event => setGoal(event.target.value)}
            onKeyDown={onGoalKeyDown}
            placeholder={copy.goalPlaceholder}
            rows={2}
            value={goal}
          />
          {active ? (
            <Button
              disabled={run?.status === 'stopping'}
              onClick={() => void stopTeamRun()}
              size="sm"
              type="button"
              variant="destructive"
            >
              <Codicon name="debug-stop" size="0.75rem" />
              {run?.status === 'stopping' ? copy.stopping : copy.stop}
            </Button>
          ) : (
            <Button disabled={!canStart} onClick={start} size="sm" type="button">
              <Codicon name="play" size="0.75rem" />
              {copy.start}
            </Button>
          )}
        </div>

        <div className="mt-1.5 flex min-h-4 items-center gap-2 text-[0.6875rem] text-muted-foreground" data-slot="team-status">
          {!gatewayOpen ? (
            <span className="text-(--ui-danger,#f87171)">{copy.notConnected}</span>
          ) : run ? (
            <>
              <span
                className={cn(
                  'font-medium',
                  run.status === 'failed' && 'text-(--ui-danger,#f87171)',
                  run.status === 'done' && 'text-primary'
                )}
              >
                {runStatusText(run, copy)}
              </span>
              <span className="min-w-0 truncate" data-slot="team-run-goal" title={run.goal}>
                {run.goal}
              </span>
              {run.error ? <span className="truncate">{run.error}</span> : null}
              {active ? <span className="truncate opacity-80">{copy.talkHint}</span> : null}
              {finalReady ? <span className="truncate opacity-80">{copy.finalReadyHint}</span> : null}
            </>
          ) : (
            <ol className="m-0 flex list-none flex-wrap gap-x-4 gap-y-0.5 p-0">
              {copy.how.map((line, i) => (
                <li className="flex items-baseline gap-1" key={line}>
                  <span className="text-primary">{i + 1}.</span>
                  <span>{line}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1 border-t border-(--ui-stroke-secondary)/60">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* The working seats take three parts of the height, the Final
              pane two: the team is what you watch, the outcome is what you
              read and question once it lands. Both scroll inside themselves. */}
          <div className="grid min-h-0 min-w-0 flex-[3_1_0%] gap-2 p-2 pb-1" style={gridStyle(size)}>
            {seats.map(index => (
              <MemberPane
                config={config.members[index]}
                index={index}
                key={index}
                locked={active}
                member={members.find(m => m.index === index)}
                onPickModel={setPicking}
                onSelect={setSelectedMember}
                selected={selectedMember === index}
              />
            ))}
          </div>
          <div className="flex min-h-0 min-w-0 flex-[2_1_0%] flex-col p-2 pt-1" data-slot="team-final-row">
            <MemberPane
              config={config.members[0]}
              index={TEAM_FINAL_INDEX}
              locked={active}
              member={finalMember}
              onPickModel={noPick}
              onSelect={setSelectedMember}
              selected={selectedMember === TEAM_FINAL_INDEX}
            />
          </div>
          {targets.length > 0 ? (
            <MemberComposer
              connected={gatewayOpen}
              disabledHint={composerHint}
              onSelectIndex={setSelectedMember}
              onSend={sendToMember}
              selectedIndex={selectedMember}
              targets={targets}
            />
          ) : null}
        </div>
        {logOpen ? (
          <aside
            className="w-72 shrink-0 overflow-y-auto border-l border-(--ui-stroke-secondary)/60 bg-(--ui-chat-surface-background)"
            data-slot="team-log-rail"
          >
            <TeamRunLog />
          </aside>
        ) : null}
      </div>

      {pickingConfig ? (
        <ModelPickerDialog
          currentModel={pickingConfig.model}
          currentProvider={pickingConfig.provider}
          gw={gateway ?? undefined}
          onOpenChange={open => {
            if (!open) {
              setPicking(null)
            }
          }}
          onSelect={selection => {
            if (picking !== null) {
              setTeamMemberModel(picking, selection)
            }
          }}
          open
          profile={profile}
        />
      ) : null}

      <ConfirmDialog
        confirmLabel={copy.resetConfirm}
        description={copy.resetBody}
        dismissOnConfirm
        onClose={() => setConfirmReset(false)}
        onConfirm={() => resetTeam()}
        open={confirmReset}
        title={copy.resetTitle}
      />
    </section>
  )
}
