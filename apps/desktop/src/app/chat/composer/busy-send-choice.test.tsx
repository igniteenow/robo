import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'

import { BusySendChoice } from './busy-send-choice'

// The choice shown when Enter is pressed on a message while Robo is working.
// Each button maps to exactly one outcome — nothing is implied by rendering.

function renderChoice() {
  const onKeep = vi.fn()
  const onQueue = vi.fn()
  const onSendNow = vi.fn()

  render(
    <I18nProvider configClient={null} initialLocale="en">
      <BusySendChoice onKeep={onKeep} onQueue={onQueue} onSendNow={onSendNow} />
    </I18nProvider>
  )

  return { onKeep, onQueue, onSendNow }
}

afterEach(() => {
  cleanup()
})

describe('BusySendChoice', () => {
  it('says Robo is still working and offers Send now / After it finishes / keep editing', () => {
    renderChoice()

    expect(screen.getByText(/Robo is still working on your last message/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Send now/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /After it finishes/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /keep editing/ })).toBeTruthy()
  })

  it('Send now sends now, and nothing else', () => {
    const { onKeep, onQueue, onSendNow } = renderChoice()

    fireEvent.click(screen.getByRole('button', { name: /Send now/ }))

    expect(onSendNow).toHaveBeenCalledTimes(1)
    expect(onQueue).not.toHaveBeenCalled()
    expect(onKeep).not.toHaveBeenCalled()
  })

  it('After it finishes queues, keep editing keeps', () => {
    const { onKeep, onQueue, onSendNow } = renderChoice()

    fireEvent.click(screen.getByRole('button', { name: /After it finishes/ }))
    fireEvent.click(screen.getByRole('button', { name: /keep editing/ }))

    expect(onQueue).toHaveBeenCalledTimes(1)
    expect(onKeep).toHaveBeenCalledTimes(1)
    expect(onSendNow).not.toHaveBeenCalled()
  })
})
