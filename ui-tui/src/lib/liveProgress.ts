import type { Msg, TodoItem } from '../types.js'

export const countPendingTodos = (todos: readonly TodoItem[]) =>
  todos.filter(todo => todo.status === 'in_progress' || todo.status === 'pending').length

export const isTodoDone = (todos: readonly TodoItem[]) =>
  todos.length > 0 && todos.every(todo => todo.status === 'completed' || todo.status === 'cancelled')

export const isToolShelfMessage = (msg: Msg | undefined) =>
  Boolean(msg?.kind === 'trail' && !msg.text && !msg.thinking?.trim() && msg.tools?.length)

export const canHoldToolShelf = (msg: Msg | undefined) =>
  Boolean(msg?.kind === 'trail' && !msg.text && (msg.thinking?.trim() || msg.tools?.length))

export const mergeToolShelfInto = (target: Msg, source: Msg): Msg => ({
  ...target,
  tools: [...(target.tools ?? []), ...(source.tools ?? [])]
})

const isBarrierMessage = (msg: Msg | undefined) => {
  if (!msg) {
    return true
  }

  // Assistant text, user input, intro/panel rows all terminate the shelf.
  if (msg.kind === 'intro' || msg.kind === 'panel' || msg.kind === 'diff') {
    return true
  }

  if (msg.role && msg.role !== 'system') {
    return true
  }

  if (msg.text) {
    return true
  }

  return false
}

const isToolCarryingTrail = (msg: Msg | undefined) => Boolean(msg?.kind === 'trail' && !msg.text && msg.tools?.length)

// A trail that already holds model reasoning — the Thinking panel of the
// current working phase. MoA reference blocks are the person's own feature,
// shown as separate entries, so they never absorb reasoning.
const isThinkingHolder = (msg: Msg | undefined) =>
  Boolean(msg?.kind === 'trail' && !msg.text && msg.thinking?.trim() && !msg.isMoaReference && !msg.todos?.length)

/**
 * Where a new piece of reasoning belongs: the Thinking panel of the working
 * phase in progress, or nowhere (a new one). Walks back from the end the same
 * way appendToolShelfMessage does for tool rows — past tool-only shelves,
 * stopping at anything a person sees as a step of the conversation (assistant
 * prose, their own message, a diff, a MoA reference). So every model call
 * between two visible updates adds to ONE Thinking panel and ONE Tool calls
 * panel, instead of opening a new "Thinking" row per call.
 */
export const findThinkingHolder = (prev: readonly Msg[]): null | number => {
  for (let index = prev.length - 1; index >= 0; index--) {
    const candidate = prev[index]

    if (isThinkingHolder(candidate)) {
      return index
    }

    if (isBarrierMessage(candidate) || candidate?.isMoaReference) {
      return null
    }
  }

  return null
}

export const joinThinking = (base: string, next: string): string => (base ? `${base}\n\n${next}` : next)

/**
 * The tool rows of the working phase in progress, lifted out of the segment
 * that holds them so the live area can draw them as one running list of
 * steps (components/streamingAssistant.tsx) instead of a folded "Tool calls
 * (N)" row that only changes its number while Robo works. The holder is the
 * same trail appendToolShelfMessage would merge the next row into — the last
 * tool-carrying trail after anything the person sees as a step of the
 * conversation — and it keeps everything else it carries (its reasoning, its
 * token tally). Render-time only: the segments themselves, what message.complete
 * writes to the transcript, and resume are untouched.
 */
export const takeLiveToolShelf = (segments: readonly Msg[]): { lines: string[]; segments: Msg[] } => {
  for (let index = segments.length - 1; index >= 0; index--) {
    const candidate = segments[index]

    if (isToolCarryingTrail(candidate)) {
      const { tools, ...rest } = candidate!
      const next = [...segments]

      next[index] = rest

      return { lines: tools ?? [], segments: next }
    }

    if (isBarrierMessage(candidate)) {
      break
    }
  }

  return { lines: [], segments: [...segments] }
}

export const appendToolShelfMessage = (prev: readonly Msg[], msg: Msg): Msg[] => {
  if (!isToolShelfMessage(msg)) {
    return [...prev, msg]
  }

  let fallbackHolder: number | null = null

  for (let index = prev.length - 1; index >= 0; index--) {
    const candidate = prev[index]

    if (isToolCarryingTrail(candidate)) {
      const next = [...prev]

      next[index] = mergeToolShelfInto(candidate!, msg)

      return next
    }

    if (fallbackHolder === null && canHoldToolShelf(candidate)) {
      fallbackHolder = index
    }

    if (isBarrierMessage(candidate)) {
      break
    }
  }

  if (fallbackHolder !== null) {
    const next = [...prev]

    next[fallbackHolder] = mergeToolShelfInto(prev[fallbackHolder]!, msg)

    return next
  }

  return [...prev, msg]
}
