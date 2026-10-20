import { atom } from 'nanostores'
import { describe, expect, it } from 'vitest'

import type { ClientSessionState } from '@/app/types'
import { type ChatMessage, textPart } from '@/lib/chat-messages'
import { createClientSessionState } from '@/lib/chat-runtime'

import {
  awaitSessionTurn,
  awaitTurnViaEvents,
  lastAssistantMessage,
  type TurnComplete,
  type TurnCompleteSource,
  turnReplyText
} from './turn'

const user = (id: string, text: string): ChatMessage => ({ id, parts: [textPart(text)], role: 'user' })

const assistant = (id: string, text: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
  id,
  parts: [textPart(text)],
  role: 'assistant',
  ...extra
})

function source() {
  const $states = atom<Record<string, ClientSessionState>>({})

  const publish = (runtimeId: string, patch: Partial<ClientSessionState>) => {
    const current = $states.get()[runtimeId] ?? createClientSessionState('stored-' + runtimeId)
    $states.set({ ...$states.get(), [runtimeId]: { ...current, ...patch } })
  }

  return { $states, publish }
}

describe('turnReplyText', () => {
  it('joins the assistant text added since the submit and surfaces an error bubble', () => {
    const messages = [user('u1', 'hi'), assistant('a1', 'old'), user('u2', 'go'), assistant('a2', 'step one'), assistant('a3', 'step two')]

    expect(turnReplyText(messages, 3)).toEqual({ text: 'step one\n\nstep two' })
    expect(turnReplyText([...messages, assistant('a4', '', { error: 'boom' })], 3)).toEqual({
      error: 'boom',
      text: 'step one\n\nstep two'
    })
  })

  it('reports no reply when nothing landed after the submit — never the previous turn’s text', () => {
    const messages = [user('u1', 'go'), assistant('a1', 'last round’s vote'), user('u2', 'next prompt')]
    expect(turnReplyText(messages, 3)).toEqual({ text: '' })
    expect(turnReplyText(messages, 2)).toEqual({ text: '' })
  })

  it('falls back to the LAST assistant message only when the transcript was renumbered', () => {
    const messages = [user('u1', 'hi'), assistant('a1', 'first reply'), user('u2', 'again'), assistant('a2', 'only reply')]
    expect(turnReplyText(messages, 10)).toEqual({ text: 'only reply' })
    expect(lastAssistantMessage([user('u1', 'x')])).toBeNull()
  })
})

describe('awaitSessionTurn', () => {
  it('resolves on the busy → idle edge with the reply text', async () => {
    const { $states, publish } = source()
    publish('rt', { busy: true, messages: [user('u1', 'go')] })

    const pending = awaitSessionTurn($states, 'rt', 1, { timeoutMs: 5000 })
    let settled = false
    void pending.then(() => {
      settled = true
    })

    publish('rt', { busy: true, messages: [user('u1', 'go'), assistant('a1', 'partial', { pending: true })] })
    await Promise.resolve()
    expect(settled).toBe(false)

    publish('rt', { busy: false, messages: [user('u1', 'go'), assistant('a1', 'final answer')] })
    const outcome = await pending

    expect(outcome).toEqual({ interrupted: false, text: 'final answer', timedOut: false })
  })

  it('resolves immediately when the session is already idle', async () => {
    const { $states, publish } = source()
    publish('rt', { busy: false, messages: [assistant('a1', 'done already')] })

    const outcome = await awaitSessionTurn($states, 'rt', 0, { timeoutMs: 5000 })
    expect(outcome.text).toBe('done already')
  })

  it('reports an interrupted turn and an error bubble', async () => {
    const { $states, publish } = source()
    publish('rt', { busy: true })

    const pending = awaitSessionTurn($states, 'rt', 0, { timeoutMs: 5000 })
    publish('rt', { busy: false, interrupted: true, messages: [assistant('a1', '', { error: 'Provider failed' })] })

    expect(await pending).toEqual({ error: 'Provider failed', interrupted: true, text: '', timedOut: false })
  })

  it('times out, keeping whatever text streamed so far', async () => {
    const { $states, publish } = source()
    publish('rt', { busy: true, messages: [assistant('a1', 'half', { pending: true })] })

    const outcome = await awaitSessionTurn($states, 'rt', 0, { timeoutMs: 10 })
    expect(outcome.timedOut).toBe(true)
    expect(outcome.error).toBe('timed out')
    expect(outcome.text).toBe('half')
  })

  it('pauses the clock while the member waits on the user, and resumes it after', async () => {
    const { $states, publish } = source()
    publish('rt', { busy: true, needsInput: true })

    const pending = awaitSessionTurn($states, 'rt', 0, { timeoutMs: 30 })
    let settled = false
    void pending.then(() => {
      settled = true
    })

    await new Promise(resolve => setTimeout(resolve, 80))
    expect(settled).toBe(false)

    // The user answered: the turn runs on and finishes normally.
    publish('rt', { busy: true, needsInput: false })
    publish('rt', { busy: false, messages: [assistant('a1', 'after approval')] })
    const outcome = await pending

    expect(outcome.timedOut).toBe(false)
    expect(outcome.text).toBe('after approval')
  })

  it('settles as stopped when the abort signal fires, and stops listening', async () => {
    const { $states, publish } = source()
    publish('rt', { busy: true })
    const controller = new AbortController()

    const pending = awaitSessionTurn($states, 'rt', 0, { signal: controller.signal, timeoutMs: 5000 })
    controller.abort()
    const outcome = await pending

    expect(outcome).toEqual({ error: 'stopped', interrupted: true, text: '', timedOut: false })

    // A later idle publish must not resolve twice or throw.
    publish('rt', { busy: false, messages: [assistant('a1', 'late')] })
    expect(await pending).toBe(outcome)
  })

  it('an already-aborted signal resolves without subscribing', async () => {
    const { $states, publish } = source()
    publish('rt', { busy: true })
    const controller = new AbortController()
    controller.abort()

    const outcome = await awaitSessionTurn($states, 'rt', 0, { signal: controller.signal, timeoutMs: 5000 })
    expect(outcome.interrupted).toBe(true)
  })
})

/** A controllable completion-event emitter for one session. */
function completeSource() {
  const listeners = new Map<string, (c: TurnComplete) => void>()

  const onComplete: TurnCompleteSource = (runtimeId, listener) => {
    listeners.set(runtimeId, listener)

    return () => listeners.delete(runtimeId)
  }

  const fire = (runtimeId: string, complete: TurnComplete) => listeners.get(runtimeId)?.(complete)

  return { fire, onComplete }
}

describe('awaitTurnViaEvents', () => {
  it('resolves on the completion event, reading the settled transcript', async () => {
    const { $states, publish } = source()
    const { fire, onComplete } = completeSource()
    publish('rt', { busy: true, messages: [user('u1', 'go')] })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 1, { timeoutMs: 5000 })

    // The real order: the event fires, THEN the store commits the final bubble
    // + flips busy. The waiter reads the committed reply a microtask later.
    fire('rt', { text: 'from the event' })
    publish('rt', { busy: false, messages: [user('u1', 'go'), assistant('a1', 'the committed answer')] })

    expect(await pending).toEqual({ interrupted: false, text: 'the committed answer', timedOut: false })
  })

  it('falls back to the event text when the stream left the final bubble empty', async () => {
    const { $states, publish } = source()
    const { fire, onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: 5000 })
    fire('rt', { text: 'only in the payload' })
    publish('rt', { busy: false })

    expect((await pending).text).toBe('only in the payload')
  })

  it('surfaces a terminal error carried by the completion event', async () => {
    const { $states, publish } = source()
    const { fire, onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: 5000 })
    fire('rt', { error: 'Provider rejected the request', text: '' })

    expect(await pending).toEqual({ error: 'Provider rejected the request', interrupted: false, text: '', timedOut: false })
  })

  it('ignores a mid-turn busy→false blip; only the completion event ends the turn', async () => {
    const { $states, publish } = source()
    const { fire, onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: 5000 }, 40)
    let settled = false
    void pending.then(() => {
      settled = true
    })

    // A spurious heartbeat between tool batches: busy false, no event, no text.
    publish('rt', { busy: false, messages: [assistant('a1', '', { pending: true })] })
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(settled).toBe(false)

    // The next model request re-arms busy (cancels the idle fallback)...
    publish('rt', { busy: true })
    await new Promise(resolve => setTimeout(resolve, 60))
    expect(settled).toBe(false)

    // ...and the real end is the completion event.
    fire('rt', { text: 'final' })
    publish('rt', { busy: false, messages: [assistant('a1', 'the full answer')] })
    expect((await pending).text).toBe('the full answer')
  })

  it('settles from state after the idle debounce when a reply is present but no completion event arrives', async () => {
    const { $states, publish } = source()
    const { onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: 5000 }, 30)
    publish('rt', { busy: false, messages: [assistant('a1', 'answer with no event')] })

    expect((await pending).text).toBe('answer with no event')
  })

  it('does NOT settle on an idle blip that left no committed reply — only a real end ends it', async () => {
    const { $states, publish } = source()
    const { fire, onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: 5000 }, 20)
    let settled = false
    void pending.then(() => {
      settled = true
    })

    // Idle with only a pending/empty bubble (a mid-turn running:false blip).
    publish('rt', { busy: false, messages: [assistant('a1', '', { pending: true })] })
    await new Promise(resolve => setTimeout(resolve, 60))
    expect(settled).toBe(false)

    fire('rt', { text: 'done' })
    publish('rt', { busy: false, messages: [assistant('a1', 'the real answer')] })
    expect((await pending).text).toBe('the real answer')
  })

  it('runs with no clock at all when the timeout is unlimited — only the real end settles it', async () => {
    const { $states, publish } = source()
    const { fire, onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: Number.POSITIVE_INFINITY }, 10)
    let settled = false
    void pending.then(() => {
      settled = true
    })

    // A long busy stretch, a needs-input pause and a resume: nothing fires.
    await new Promise(resolve => setTimeout(resolve, 30))
    publish('rt', { busy: true, needsInput: true })
    await new Promise(resolve => setTimeout(resolve, 10))
    publish('rt', { busy: true, needsInput: false })
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(settled).toBe(false)

    fire('rt', { text: 'took its time' })
    publish('rt', { busy: false, messages: [assistant('a1', 'took its time')] })
    expect(await pending).toEqual({ interrupted: false, text: 'took its time', timedOut: false })
  })

  it('an idle seat with no reply and no event is settled after the stall window — a lost event cannot hang an unlimited turn', async () => {
    const { $states, publish } = source()
    const { onComplete } = completeSource()
    publish('rt', { busy: true, messages: [user('u1', 'go')] })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 1, { timeoutMs: Number.POSITIVE_INFINITY }, 10, 60)
    let settled = false
    void pending.then(() => {
      settled = true
    })

    // The reconnect gap: busy false, an empty bubble, and the completion
    // event never comes. The short debounce must NOT fire (it is a blip as
    // far as anyone can tell)...
    publish('rt', { busy: false, messages: [user('u1', 'go'), assistant('a1', '', { pending: true })] })
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(settled).toBe(false)

    // ...but the stall window does, as no reply.
    await new Promise(resolve => setTimeout(resolve, 60))
    expect(settled).toBe(true)
    expect((await pending).text).toBe('')
  })

  it('a reply that commits during the stall window shortens the wait to the settle debounce', async () => {
    const { $states, publish } = source()
    const { onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: Number.POSITIVE_INFINITY }, 10, 10_000)
    publish('rt', { busy: false, messages: [assistant('a1', '', { pending: true })] })
    await new Promise(resolve => setTimeout(resolve, 20))
    publish('rt', { busy: false, messages: [assistant('a1', 'late but here')] })

    expect((await pending).text).toBe('late but here')
  })

  it('settles at once on a terminal error bubble that arrives with no completion event', async () => {
    const { $states, publish } = source()
    const { onComplete } = completeSource()
    publish('rt', { busy: true, messages: [user('u1', 'go')] })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 1, { timeoutMs: 5000 }, 10_000)
    // The gateway's bare `error` event: an empty assistant bubble carrying the
    // error, busy false, and no `message.complete` ever.
    publish('rt', {
      busy: false,
      messages: [user('u1', 'go'), assistant('a1', '', { error: 'agent init failed: access denied' })]
    })

    expect(await pending).toEqual({
      error: 'agent init failed: access denied',
      interrupted: false,
      text: '',
      timedOut: false
    })
  })

  it('settles at once on a deliberate interrupt, without waiting for the debounce', async () => {
    const { $states, publish } = source()
    const { onComplete } = completeSource()
    publish('rt', { busy: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: 5000 }, 10_000)
    publish('rt', { busy: false, interrupted: true, messages: [assistant('a1', 'partial')] })

    const outcome = await pending
    expect(outcome.interrupted).toBe(true)
    expect(outcome.timedOut).toBe(false)
  })

  it('times out, and the clock pauses while the member waits on the user', async () => {
    const { $states, publish } = source()
    const { onComplete } = completeSource()
    publish('rt', { busy: true, needsInput: true })

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { timeoutMs: 30 }, 5000)
    let settled = false
    void pending.then(() => {
      settled = true
    })

    await new Promise(resolve => setTimeout(resolve, 70))
    expect(settled).toBe(false)

    publish('rt', { busy: true, needsInput: false })
    expect((await pending).timedOut).toBe(true)
  })

  it('settles as stopped on abort and stops listening to later events', async () => {
    const { $states, publish } = source()
    const { fire, onComplete } = completeSource()
    publish('rt', { busy: true })
    const controller = new AbortController()

    const pending = awaitTurnViaEvents(onComplete, $states, 'rt', 0, { signal: controller.signal, timeoutMs: 5000 })
    controller.abort()
    const outcome = await pending
    expect(outcome).toEqual({ error: 'stopped', interrupted: true, text: '', timedOut: false })

    fire('rt', { text: 'late' })
    publish('rt', { busy: false, messages: [assistant('a1', 'late answer')] })
    expect(await pending).toBe(outcome)
  })
})
