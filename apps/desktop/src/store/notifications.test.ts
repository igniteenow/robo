import { beforeEach, expect, test } from 'vitest'

import {
  $notifications,
  clearAllNotifications,
  clearNotifications,
  isDiskFullErrorMessage,
  notify,
  notifyError
} from './notifications'

beforeEach(() => {
  clearAllNotifications()
})

function lastMessage(): string {
  return $notifications.get()[0]?.message ?? ''
}

// Regression for #39365: a gateway auth 401 (bad API_SERVER_KEY) must not be
// summarized as a provider (OpenAI/OpenRouter) API key problem.
test('gateway_auth_failed error is summarized as gateway auth, not provider key', () => {
  notifyError(
    new Error(
      '401 {"error": {"message": "Invalid gateway API key (API_SERVER_KEY)", "type": "gateway_auth_error", "code": "gateway_auth_failed"}}'
    ),
    'Request failed'
  )

  expect(lastMessage()).toContain('API_SERVER_KEY')
  expect(lastMessage()).not.toMatch(/OpenAI/i)
})

test('provider invalid_api_key error still maps to the OpenAI summary', () => {
  notifyError(
    new Error('401 {"error": {"message": "Incorrect API key provided", "code": "invalid_api_key"}}'),
    'Request failed'
  )

  expect(lastMessage()).toMatch(/OpenAI rejected the API key/i)
})

test('disk-full / ENOSPC errors toast a free-space message', () => {
  expect(isDiskFullErrorMessage('OSError: [Errno 28] No space left on device')).toBe(true)
  expect(isDiskFullErrorMessage('sqlite3.OperationalError: database or disk is full')).toBe(true)
  expect(isDiskFullErrorMessage('disk full: session storage could not be written — free some disk space')).toBe(true)
  expect(isDiskFullErrorMessage('This is often a full disk — free some space')).toBe(true)
  expect(isDiskFullErrorMessage('session storage could not be written: permission denied')).toBe(false)
  expect(isDiskFullErrorMessage('network timeout')).toBe(false)

  notifyError(new Error('OSError: [Errno 28] No space left on device: state.db'), 'Prompt failed')

  expect(lastMessage()).toMatch(/Disk full/i)
  expect(lastMessage()).toMatch(/free some space/i)
})

test('session storage write failure is treated as disk-full class', () => {
  notifyError(
    new Error('disk full: session storage could not be written — free some disk space and try again'),
    'Prompt failed'
  )

  expect(lastMessage()).toMatch(/Disk full/i)
})

// Opening or switching a chat clears that chat's notifications. It must not
// clear news about Robo itself: the update popup was cleared (and, because
// clearing counts as closing, snoozed for a day) right after every launch.
test('opening a chat clears chat notifications but keeps app ones, without closing them', () => {
  const closed: string[] = []

  notify({ id: 'update', message: 'Update ready', onDismiss: () => closed.push('update'), scope: 'app' })
  notify({ id: 'saved', message: 'Saved', onDismiss: () => closed.push('saved') })

  clearNotifications()

  expect($notifications.get().map(item => item.id)).toEqual(['update'])
  expect(closed).toEqual(['saved'])
})

test('Clear all still clears app notifications too', () => {
  const closed: string[] = []

  notify({ id: 'update', message: 'Update ready', onDismiss: () => closed.push('update'), scope: 'app' })
  clearAllNotifications()

  expect($notifications.get()).toEqual([])
  expect(closed).toEqual(['update'])
})

test('a burst of chat notifications never pushes out an app one', () => {
  notify({ id: 'update', message: 'Update ready', scope: 'app' })

  for (let i = 0; i < 6; i++) {
    notify({ id: `chat-${i}`, message: `chat ${i}` })
  }

  const ids = $notifications.get().map(item => item.id)

  expect(ids).toContain('update')
  expect(ids).toHaveLength(4)
  expect(ids.slice(0, 3)).toEqual(['chat-5', 'chat-4', 'chat-3'])
})

test('notifications are chat-scoped unless they say otherwise', () => {
  notify({ id: 'plain', message: 'plain' })

  expect($notifications.get()[0]?.scope).toBe('session')
})
