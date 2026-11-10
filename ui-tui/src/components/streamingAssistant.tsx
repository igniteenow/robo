import { useStore } from '@nanostores/react'
import { Box } from '@robo/ink'
import { memo } from 'react'

import type { AppLayoutProgressProps } from '../app/interfaces.js'
import { toggleTodoCollapsed, useTurnSelector } from '../app/turnStore.js'
import { $uiState } from '../app/uiStore.js'
import { blockRenders, hasLeadGap } from '../domain/blockLayout.js'
import { sectionMode } from '../domain/details.js'
import { appendToolShelfMessage, findThinkingHolder, takeLiveToolShelf } from '../lib/liveProgress.js'
import { ANALYZING_TRAIL_LINE, isTransientTrailLine } from '../lib/text.js'
import { PHASE_VERBS } from '../lib/toolPhrase.js'
import type { ActiveTool, ActivityItem, DetailsMode, Msg, SectionVisibility } from '../types.js'

import { MessageLine } from './messageLine.js'
import { PhaseRow } from './thinking.js'
import { TodoPanel } from './todoPanel.js'

const groupedSegments = (segments: Msg[]): Msg[] =>
  segments.reduce<Msg[]>((acc, msg) => appendToolShelfMessage(acc, msg), [])

interface LiveBlock {
  isStreaming?: boolean
  key: string
  // The live list of steps for the working phase in progress (ToolTrail.live).
  live?: boolean
  msg: Msg
  phase?: string
  phaseTone?: ActivityItem['tone']
  // This block holds the reasoning the model is writing right now.
  reasoningLive?: boolean
  tools?: ActiveTool[]
}

/**
 * What Robo is doing while no tool runs, for the last row of the live list
 * of steps: a phase the gateway reported (the end-of-turn fact check, a
 * memory save) when there is one, else what can be inferred. Empty when a
 * row already says it (a running or drafting step) or the answer itself is
 * streaming in under the list — a reported phase then gets its own row under
 * the answer instead (see StreamingAssistant).
 */
export const livePhase = (state: {
  drafting: boolean
  reasoning: boolean
  reported?: string
  running: boolean
  streaming: boolean
  trail: readonly string[]
}): string => {
  if (state.running || state.drafting || state.streaming) {
    return ''
  }

  if (state.reported) {
    return state.reported
  }

  if (!state.reasoning && state.trail.includes(ANALYZING_TRAIL_LINE)) {
    return ANALYZING_TRAIL_LINE
  }

  return `${PHASE_VERBS.thinking}…`
}

export const StreamingAssistant = memo(function StreamingAssistant({
  cols,
  compact,
  detailsMode,
  detailsModeCommandOverride,
  prevMsg,
  progress,
  sections
}: StreamingAssistantProps) {
  const ui = useStore($uiState)
  const streamSegments = useTurnSelector(state => state.streamSegments)
  const streamPendingTools = useTurnSelector(state => state.streamPendingTools)
  const streaming = useTurnSelector(state => state.streaming)
  const activeTools = useTurnSelector(state => state.tools)
  const turnTrail = useTurnSelector(state => state.turnTrail)
  const reasoningActive = useTurnSelector(state => state.reasoningActive)
  const reasoningStreaming = useTurnSelector(state => state.reasoningStreaming)
  const reportedPhase = useTurnSelector(state => state.phase)
  const showStreamingArea = Boolean(streaming)

  if (!progress.showProgressArea && !showStreamingArea && !activeTools.length) {
    return null
  }

  // A phase the gateway reported while the turn runs — the fact check after
  // the answer streamed, a verification pass, a memory save, a compaction.
  const phase = ui.busy ? reportedPhase : null

  // While the turn runs with the tools section collapsed (the default), the
  // steps of the working phase in progress draw as one live list — every
  // call so far with its ✓/✗ and duration, the running one with a clock,
  // then what Robo is doing between calls — instead of a folded
  // "Tool calls (N)" row whose only movement is its number. The rows are
  // lifted out of the segment that holds them at render time; the segments,
  // the transcript message.complete writes, and resume are untouched, and
  // the folded row is what the settled transcript shows.
  const liveSteps = ui.busy && sectionMode('tools', detailsMode, sections, detailsModeCommandOverride) === 'collapsed'

  let segments = groupedSegments(streamSegments)
  let stepLines: string[] = []

  if (liveSteps) {
    const lifted = takeLiveToolShelf(segments)

    segments = lifted.segments
    // `turnTrail` holds the transient rows (a call the model is still
    // drafting, "analyzing tool output…"); the latter becomes the phase row.
    stepLines = [...lifted.lines, ...streamPendingTools, ...turnTrail.filter(line => line !== ANALYZING_TRAIL_LINE)]
  }

  const thinkingHolder = ui.busy && reasoningActive ? findThinkingHolder(segments) : null

  // Flatten the live area into one ordered list so each block's leading gap
  // can be derived from the block directly above it — including the boundary
  // back into settled history (prevMsg). Tracking the predecessor rather than
  // the live text is what keeps the streaming block from jumping when it
  // flushes into a settled segment.
  const blocks: LiveBlock[] = segments.map((msg, i) => ({
    key: `seg:${i}`,
    msg,
    ...(i === thinkingHolder && { reasoningLive: true })
  }))

  // The reported phase rides as the last row of the live list when the list
  // is the newest thing on screen; under a streaming answer it gets its own
  // row below the text instead, where the eye is.
  let phaseInList = false

  if (liveSteps && (stepLines.length || activeTools.length)) {
    const drafting = stepLines.some(line => isTransientTrailLine(line))

    phaseInList = Boolean(phase) && !showStreamingArea && !activeTools.length && !drafting

    blocks.push({
      key: 'live-steps',
      live: true,
      msg: { kind: 'trail', role: 'system', text: '', tools: stepLines },
      phase: livePhase({
        drafting,
        reasoning: reasoningActive,
        running: activeTools.length > 0,
        streaming: showStreamingArea,
        trail: turnTrail,
        ...(phaseInList && { reported: phase!.text })
      }),
      ...(phaseInList && { phaseTone: phase!.tone }),
      tools: activeTools
    })
  } else if (activeTools.length) {
    blocks.push({ key: 'active-tools', msg: { kind: 'trail', role: 'system', text: '' }, tools: activeTools })
  }

  if (showStreamingArea) {
    blocks.push({
      isStreaming: true,
      key: 'streaming',
      msg: {
        role: 'assistant',
        text: streaming,
        ...(!liveSteps && streamPendingTools.length && { tools: streamPendingTools })
      }
    })
  } else if (!liveSteps && streamPendingTools.length) {
    blocks.push({ key: 'pending-tools', msg: { kind: 'trail', role: 'system', text: '', tools: streamPendingTools } })
  }

  const standalonePhase = phase && !phaseInList && !activeTools.length ? phase : null

  const detailsCtx = { commandOverride: detailsModeCommandOverride, detailsMode, sections }
  let prev = prevMsg

  return (
    <>
      {blocks.map(block => {
        const node = (
          <MessageLine
            cols={cols}
            compact={compact}
            detailsMode={detailsMode}
            detailsModeCommandOverride={detailsModeCommandOverride}
            isStreaming={block.isStreaming}
            key={block.key}
            live={block.live}
            msg={block.msg}
            phase={block.phase}
            phaseTone={block.phaseTone}
            prev={prev}
            reasoningLive={block.reasoningLive}
            reasoningStreaming={reasoningStreaming}
            sections={sections}
            t={ui.theme}
            {...(block.tools ? { tools: block.tools } : {})}
          />
        )

        // Advance the grouping predecessor only past blocks that actually
        // paint, so a trail hidden by /details stays transparent here too
        // (active tools live in the prop, so fold them into the check).
        const checkMsg = block.tools?.length ? { ...block.msg, tools: block.tools.map(tool => tool.name) } : block.msg

        if (blockRenders(checkMsg, detailsCtx)) {
          prev = block.msg
        }

        return node
      })}
      {standalonePhase ? (
        // Its own row under whatever is newest — the streamed answer, the
        // folded trail of an opened panel — with the usual blank line where
        // the band changes from prose to the working area.
        <Box marginTop={hasLeadGap(prev, PHASE_ROW_MSG) ? 1 : 0}>
          <PhaseRow t={ui.theme} text={standalonePhase.text} tone={standalonePhase.tone} />
        </Box>
      ) : null}
    </>
  )
})

// The phase row sits in the trail band for spacing purposes.
const PHASE_ROW_MSG: Pick<Msg, 'kind' | 'role'> = { kind: 'trail', role: 'system' }

export const LiveTodoPanel = memo(function LiveTodoPanel() {
  const ui = useStore($uiState)
  const todos = useTurnSelector(state => state.todos)
  const collapsed = useTurnSelector(state => state.todoCollapsed)

  return <TodoPanel collapsed={collapsed} onToggle={toggleTodoCollapsed} t={ui.theme} todos={todos} />
})

interface StreamingAssistantProps {
  cols: number
  compact?: boolean
  detailsMode: DetailsMode
  detailsModeCommandOverride: boolean
  prevMsg?: Msg
  progress: AppLayoutProgressProps
  sections?: SectionVisibility
}
