import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $hapticsMuted } from '@/store/haptics'
import { resetVoiceConversation, setVoiceConversationView } from '@/store/voice-conversation'

import { registerHapticTrigger, triggerHaptic } from './haptics'

// web-haptics renders pulses as audio; on speakers that is a click. A voice
// chat is silent apart from Robo talking, so haptics stay off while one is on.

const trigger = vi.fn(() => undefined)

beforeEach(() => {
  trigger.mockClear()
  $hapticsMuted.set(false)
  resetVoiceConversation()
  registerHapticTrigger(trigger)
})

afterEach(() => {
  registerHapticTrigger(null)
  resetVoiceConversation()
})

describe('triggerHaptic', () => {
  it('fires normally outside a voice chat', () => {
    triggerHaptic('submit')
    expect(trigger).toHaveBeenCalledTimes(1)
  })

  it('stays silent for the whole voice chat, then comes back', () => {
    setVoiceConversationView({ active: true, level: 0, muted: false, status: 'listening' })
    triggerHaptic('submit')
    triggerHaptic('streamStart')
    triggerHaptic('streamDone')
    expect(trigger).not.toHaveBeenCalled()

    resetVoiceConversation()
    triggerHaptic('submit')
    expect(trigger).toHaveBeenCalledTimes(1)
  })

  it('respects the mute toggle', () => {
    $hapticsMuted.set(true)
    triggerHaptic('submit')
    expect(trigger).not.toHaveBeenCalled()
  })
})
