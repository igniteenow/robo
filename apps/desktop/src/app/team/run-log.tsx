/**
 * The team's running record: rounds, every reviewer's ranking with its
 * reason, each decision and how it was reached, side tasks, and the final
 * answer. Lines are phrased here from the entry's `kind`/`code` so the page
 * stays localized; the model-written parts (options, reasons, summaries) are
 * shown verbatim.
 */

import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'

import { Codicon } from '@/components/ui/codicon'
import { CopyButton } from '@/components/ui/copy-button'
import { EmptyState } from '@/components/ui/empty-state'
import { useI18n } from '@/i18n'
import { TEAM_FINAL_INDEX } from '@/lib/team/protocol'
import { cn } from '@/lib/utils'
import { $teamRun, type TeamLogEntry } from '@/store/team'

const KIND_ICON: Record<TeamLogEntry['kind'], string> = {
  decision: 'check',
  error: 'error',
  final: 'star-full',
  note: 'info',
  round: 'debug-step-over',
  side: 'tools',
  vote: 'checklist'
}

export function describeEntry(entry: TeamLogEntry, copy: ReturnType<typeof useI18n>['t']['team']): string {
  const name =
    entry.memberIndex === undefined
      ? ''
      : entry.memberIndex === TEAM_FINAL_INDEX
        ? copy.final
        : entry.memberIndex === 0
          ? copy.lead
          : copy.reviewer(entry.memberIndex + 1)

  const e = copy.entry

  switch (entry.kind) {
    case 'round':
      return e.round(entry.round)

    case 'vote':
      return e.vote(name, entry.text)
    case 'decision': {
      const how = entry.code && entry.code in e.decidedBy ? e.decidedBy[entry.code as keyof typeof e.decidedBy] : ''

      return how ? `${e.decision(entry.text)} — ${how}` : e.decision(entry.text)
    }

    case 'side':
      return entry.code === 'sideTaskAssigned' ? e.sideTaskAssigned(name) : e.sideResult(name)

    case 'error':
      return e.error(name)

    case 'final':
      return e.final
    case 'note':
      switch (entry.code) {
        case 'noVote':
          return e.noVote(name)

        case 'reviewerFailed':
          return e.reviewerFailed(name)

        case 'repair':
          return e.repair

        case 'leadInterrupted':
          return e.leadInterrupted

        case 'roundsExhausted':
          return e.roundsExhausted

        case 'finalFallback':
          return e.finalFallback

        case 'completionAccepted':
          return e.completionAccepted

        case 'completionPushback':
          return e.completionPushback

        case 'completionExhausted':
          return e.completionExhausted

        case 'completionNoVerdict':
          return e.completionNoVerdict

        case 'completionSkipped':
          return e.completionSkipped

        case 'sideTaskSkipped':
          return e.sideTaskSkipped

        case 'sideTaskFailed':
          return e.sideTaskFailed(name)

        default:
          return entry.text
      }

    default:
      return entry.text
  }
}

function LogLine({ entry }: { entry: TeamLogEntry }) {
  const { t } = useI18n()
  const copy = t.team
  const headline = describeEntry(entry, copy)

  // The decision line already names the winner, and the final line's text is
  // the outcome itself — shown once, in the answer box with its copy button
  // below the list, not again here; everything else shows its model-written
  // text below the headline.
  const body =
    entry.kind === 'decision' || entry.kind === 'vote' || entry.kind === 'round' || entry.kind === 'final'
      ? ''
      : entry.text

  return (
    <li
      className={cn(
        'grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 py-1.5 text-xs',
        entry.kind === 'round' && 'mt-2 border-t border-(--ui-stroke-secondary)/60 pt-2 first:mt-0 first:border-t-0',
        entry.kind === 'error' && 'text-(--ui-danger,#f87171)'
      )}
      data-log-kind={entry.kind}
    >
      <Codicon
        className={cn(
          'mt-0.5',
          entry.kind === 'decision' || entry.kind === 'final' ? 'text-primary' : 'text-muted-foreground/70'
        )}
        name={KIND_ICON[entry.kind]}
        size="0.75rem"
      />
      <div className="min-w-0">
        <div className={cn('break-words', (entry.kind === 'round' || entry.kind === 'decision' || entry.kind === 'final') && 'font-medium')}>
          {headline}
        </div>
        {body ? <div className="mt-0.5 whitespace-pre-wrap break-words text-muted-foreground">{body}</div> : null}
        {entry.detail ? (
          <div className="mt-0.5 whitespace-pre-wrap break-words text-[0.6875rem] text-muted-foreground/80">{entry.detail}</div>
        ) : null}
      </div>
    </li>
  )
}

function FinalAnswer({ text }: { text: string }) {
  const { t } = useI18n()
  const copy = t.team

  return (
    <div className="mt-2 rounded-lg bg-(--ui-bg-tertiary) p-3 text-xs" data-slot="team-final-answer">
      <div className="mb-1 flex items-center gap-2">
        <Codicon className="text-primary" name="star-full" size="0.75rem" />
        <span className="font-medium">{copy.finalAnswer}</span>
        <CopyButton appearance="inline" className="ml-auto" label={copy.copyFinal} showLabel text={text} />
      </div>
      <div className="whitespace-pre-wrap break-words">{text}</div>
    </div>
  )
}

/** The nearest scrolling ancestor (the log rail), or null. */
function scrollParent(node: HTMLElement): HTMLElement | null {
  for (let el = node.parentElement; el; el = el.parentElement) {
    const { overflowY } = getComputedStyle(el)

    if (overflowY === 'auto' || overflowY === 'scroll') {
      return el
    }
  }

  return null
}

/** How close to the bottom (px) still counts as "following" the log. */
const FOLLOW_SLACK_PX = 48

export function TeamRunLog() {
  const { t } = useI18n()
  const copy = t.team
  const run = useStore($teamRun)
  const endRef = useRef<HTMLDivElement | null>(null)
  const lastHeightRef = useRef<null | number>(null)
  const count = run?.log.length ?? 0

  // Follow the newest line, like a transcript — but only while the reader is
  // at the bottom. Someone who scrolled up to reread an earlier decision is
  // not yanked down by every vote that lands; they catch up when they return.
  // eslint-disable-next-line no-restricted-syntax -- legitimate DOM measurement ref (the rail's last scroll height), not an atom mirror
  useEffect(() => {
    const end = endRef.current
    const rail = end ? scrollParent(end) : null

    if (!end || !rail) {
      end?.scrollIntoView?.({ block: 'end' })

      return
    }

    // Distance from the bottom as it stood BEFORE this line was added; the
    // first paint (the rail just opened) always lands on the newest line.
    const heightBefore = lastHeightRef.current
    lastHeightRef.current = rail.scrollHeight

    const wasFollowing =
      heightBefore === null || heightBefore - rail.scrollTop - rail.clientHeight < FOLLOW_SLACK_PX

    if (wasFollowing) {
      end.scrollIntoView?.({ block: 'end' })
    }
  }, [count, run?.final])

  if (!run) {
    return <EmptyState className="min-h-32" description={copy.logEmpty} title={copy.log} />
  }

  // The goal heads the record: the goal box clears when a run starts (like a
  // chat composer), so this is where the running goal stays readable in full.
  return (
    <div className="px-3 py-2" data-slot="team-log">
      <div className="mb-2 break-words text-xs" data-slot="team-log-goal">
        <span className="text-muted-foreground">{copy.goalLabel}: </span>
        <span className="font-medium">{run.goal}</span>
      </div>
      {run.log.length === 0 ? (
        <div className="text-xs text-muted-foreground">{copy.logEmpty}</div>
      ) : (
        <ul className="m-0 list-none p-0">
          {run.log.map(entry => (
            <LogLine entry={entry} key={entry.id} />
          ))}
        </ul>
      )}
      {run.final ? <FinalAnswer text={run.final} /> : null}
      {run.error ? (
        <div className="mt-2 break-words text-xs text-(--ui-danger,#f87171)" data-slot="team-error">
          {run.error}
        </div>
      ) : null}
      <div ref={endRef} />
    </div>
  )
}
