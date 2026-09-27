import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { $updateApply, $updateOverlayOpen, $updateOverlayTarget, resetUpdateApplyState } from '@/store/updates'

import { UpdatesOverlay } from './updates-overlay'

const originalPlatform = window.navigator.platform

function setPlatform(value: string) {
  Object.defineProperty(window.navigator, 'platform', { configurable: true, value })
}

function openManualCard() {
  act(() => {
    $updateOverlayTarget.set('client')
    $updateApply.set({
      applying: false,
      command: 'robo update',
      error: null,
      log: [],
      message: 'robo update',
      percent: null,
      stage: 'manual'
    })
    $updateOverlayOpen.set(true)
  })
}

afterEach(() => {
  cleanup()
  act(() => {
    $updateOverlayOpen.set(false)
    resetUpdateApplyState()
  })
  setPlatform(originalPlatform)
})

describe('manual update card', () => {
  it('tells Windows users to quit Robo before running the command', () => {
    setPlatform('Win32')
    render(<UpdatesOverlay />)
    openManualCard()

    // The command can use PowerShell's call operator, so name that shell.
    expect(screen.getByText(/Quit Robo first.*PowerShell/)).toBeTruthy()
    expect(screen.getByText('robo update')).toBeTruthy()
  })

  it('keeps the plain instruction on macOS and Linux', () => {
    setPlatform('Linux x86_64')
    render(<UpdatesOverlay />)
    openManualCard()

    expect(screen.getByText(/Paste this into your terminal/)).toBeTruthy()
    expect(screen.queryByText(/Quit Robo first/)).toBeNull()
  })
})
