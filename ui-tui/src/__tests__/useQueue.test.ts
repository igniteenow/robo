import { describe, expect, it } from 'vitest'

import { dequeueItem, prependQueueItem, queueItem, removeAtInPlace, takeQueueItem } from '../hooks/useQueue.js'

describe('dequeueItem', () => {
  it('returns the full item — text AND display — not just text', () => {
    // The actual bug: a caller that only forwards `.text` shows the wrong
    // thing (or the collapsed-paste label instead of real content) once a
    // queued item with a different display is finally sent.
    const queue = [queueItem('the real submit text', 'what the user actually typed')]

    expect(dequeueItem(queue)).toEqual({
      display: 'what the user actually typed',
      text: 'the real submit text'
    })
  })

  it('removes the head from the queue (FIFO)', () => {
    const queue = [queueItem('first'), queueItem('second'), queueItem('third')]

    expect(dequeueItem(queue)).toEqual(queueItem('first'))
    expect(queue).toEqual([queueItem('second'), queueItem('third')])
  })

  it('returns undefined on an empty queue, without throwing', () => {
    expect(dequeueItem([])).toBeUndefined()
  })

  it('a simple typed message with no expansion has identical text/display', () => {
    // Sanity check for the common case (plain typed text, no /skill
    // expansion or file-drop rewrite) — text and display should match.
    const queue = [queueItem('hello')]
    const item = dequeueItem(queue)

    expect(item?.text).toBe('hello')
    expect(item?.display).toBe('hello')
  })
})

describe('removeAtInPlace', () => {
  it('removes the item at the given index in place', () => {
    const arr = ['a', 'b', 'c']

    removeAtInPlace(arr, 1)
    expect(arr).toEqual(['a', 'c'])
  })

  it('is a no-op when the index is out of bounds', () => {
    const arr = ['a', 'b']

    removeAtInPlace(arr, -1)
    removeAtInPlace(arr, 5)
    expect(arr).toEqual(['a', 'b'])
  })

  it('returns the same reference (mutates in place)', () => {
    const arr = ['x']
    const same = removeAtInPlace(arr, 0)

    expect(same).toBe(arr)
    expect(arr).toEqual([])
  })
})

describe('queue items', () => {
  it('keeps execution text and collapsed display together through edit and requeue', () => {
    const display = '[[ first.. [3 lines] .. last ]]'
    const text = 'first\nmiddle\nlast'
    const queue = [queueItem(text, display), queueItem('next')]

    const edited = takeQueueItem(queue, 0, `before ${display} after`)

    expect(edited).toEqual({
      display: `before ${display} after`,
      text: `before ${text} after`
    })
    expect(queue).toEqual([queueItem('next')])

    prependQueueItem(queue, edited!)
    expect(queue[0]).toEqual({
      display: `before ${display} after`,
      text: `before ${text} after`
    })
  })

  it('treats a rewritten collapsed label as literal edited text', () => {
    const queue = [queueItem('full payload', '[[ collapsed ]]')]

    expect(takeQueueItem(queue, 0, 'replacement')).toEqual(queueItem('replacement'))
  })
})
