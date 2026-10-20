import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TEAM_FINAL_INDEX } from '@/lib/team/protocol'

import { type ComposerTarget, MemberComposer } from './member-composer'

const bound = (index: number, name: string): ComposerTarget => ({ index, name, runtimeId: `rt-${index}` })

function setup(overrides: Partial<Parameters<typeof MemberComposer>[0]> = {}) {
  const onSend = vi.fn(async () => undefined)
  const onSelectIndex = vi.fn()

  const props = {
    connected: true,
    onSelectIndex,
    onSend,
    selectedIndex: 0,
    targets: [bound(0, 'Lead'), bound(1, 'Reviewer 2')],
    ...overrides
  }

  render(<MemberComposer {...props} />)

  return { onSelectIndex, onSend }
}

afterEach(cleanup)

describe('MemberComposer', () => {
  it('sends the typed message to the selected member on Enter and clears the box', async () => {
    const { onSend } = setup()
    const input = screen.getByLabelText('Message a member') as HTMLTextAreaElement

    fireEvent.change(input, { target: { value: '  check the storage layer  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(onSend).toHaveBeenCalledWith(0, 'check the storage layer'))
    await waitFor(() => expect(input.value).toBe(''))
  })

  it('sends to whichever seat is selected', async () => {
    const { onSend } = setup({ selectedIndex: 1 })
    const input = screen.getByLabelText('Message a member')

    fireEvent.change(input, { target: { value: 'hi reviewer' } })
    fireEvent.click(screen.getByRole('button', { name: /Send/ }))

    await waitFor(() => expect(onSend).toHaveBeenCalledWith(1, 'hi reviewer'))
  })

  it('Shift+Enter inserts a newline instead of sending', () => {
    const { onSend } = setup()
    const input = screen.getByLabelText('Message a member')

    fireEvent.change(input, { target: { value: 'line one' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })

    expect(onSend).not.toHaveBeenCalled()
  })

  it('will not send an empty or whitespace-only message', () => {
    const { onSend } = setup()
    const input = screen.getByLabelText('Message a member')
    const button = screen.getByRole('button', { name: /Send/ }) as HTMLButtonElement

    expect(button.disabled).toBe(true)
    fireEvent.change(input, { target: { value: '   ' } })
    expect(button.disabled).toBe(true)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSend).not.toHaveBeenCalled()
  })

  it('keeps the typed message when the send fails, for a retry', async () => {
    const onSend = vi.fn(async () => {
      throw new Error('offline')
    })

    render(<MemberComposer connected onSelectIndex={vi.fn()} onSend={onSend} selectedIndex={0} targets={[bound(0, 'Lead')]} />)
    const input = screen.getByLabelText('Message a member') as HTMLTextAreaElement

    fireEvent.change(input, { target: { value: 'keep me' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(onSend).toHaveBeenCalled())
    expect(input.value).toBe('keep me')
  })

  it('switches the target through the member chips', () => {
    const { onSelectIndex } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Reviewer 2' }))
    expect(onSelectIndex).toHaveBeenCalledWith(1)
  })

  it('marks the selected chip pressed', () => {
    setup({ selectedIndex: 1 })
    expect((screen.getByRole('button', { name: 'Lead' }) as HTMLButtonElement).getAttribute('aria-pressed')).toBe('false')
    expect((screen.getByRole('button', { name: 'Reviewer 2' }) as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true')
  })

  it('offers the Final outcome as a target and addresses it by name', async () => {
    const { onSend, onSelectIndex } = setup({
      selectedIndex: TEAM_FINAL_INDEX,
      targets: [bound(0, 'Lead'), bound(TEAM_FINAL_INDEX, 'Final outcome')]
    })

    const input = screen.getByLabelText('Message a member') as HTMLTextAreaElement

    expect(input.getAttribute('placeholder')).toBe('Message Final outcome…')
    fireEvent.change(input, { target: { value: 'why Postgres over SQLite?' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(TEAM_FINAL_INDEX, 'why Postgres over SQLite?'))

    fireEvent.click(screen.getByRole('button', { name: 'Lead' }))
    expect(onSelectIndex).toHaveBeenCalledWith(0)
  })

  it('is disabled with a hint when the selected seat has no live session', () => {
    setup({ selectedIndex: 0, targets: [{ index: 0, name: 'Lead', runtimeId: null }] })
    const input = screen.getByLabelText('Message a member') as HTMLTextAreaElement

    expect(input.disabled).toBe(true)
    expect(input.getAttribute('placeholder')).toBe('Start the team to message a member')
  })

  it('is disabled while the gateway is closed', () => {
    setup({ connected: false })
    expect((screen.getByLabelText('Message a member') as HTMLTextAreaElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: /Send/ }) as HTMLButtonElement).disabled).toBe(true)
  })
})
