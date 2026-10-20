import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReadableAtom } from 'nanostores'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createClientSessionState } from '@/lib/chat-runtime'
import { TEAM_FINAL_INDEX } from '@/lib/team/protocol'
import { $gatewayState } from '@/store/session'
import { $sessionStates } from '@/store/session-states'
import {
  $teamConfig,
  $teamMembers,
  $teamRun,
  appendTeamLog,
  createTeamMember,
  createTeamRun,
  resetTeamConfig,
  setTeamLogOpen,
  setTeamMemberModel
} from '@/store/team'

import { TeamPage } from './page'

const controller = vi.hoisted(() => ({
  resetTeam: vi.fn(async () => undefined),
  startTeamRun: vi.fn(async () => true),
  stopTeamRun: vi.fn(async () => undefined),
  submitTeamPrompt: vi.fn(async () => undefined)
}))

vi.mock('./controller', () => controller)

// The member chat is the real tile surface (ChatView + composer); the page
// test only needs to know it mounts for a bound seat.
vi.mock('@/app/chat/session-tile', () => ({
  buildTileView: (_storedSessionId: string, $runtimeId: ReadableAtom<null | string>) => ({ $runtimeId }),
  TileChat: ({ runtimeId }: { runtimeId: string }) => <div data-testid="tile-chat">{runtimeId}</div>
}))

// The real picker calls onSelect, then closes itself through onOpenChange.
vi.mock('@/components/model-picker', () => ({
  ModelPickerDialog: ({
    currentModel,
    onOpenChange,
    onSelect,
    open
  }: {
    currentModel: string
    onOpenChange: (open: boolean) => void
    onSelect: (selection: { model: string; provider: string }) => void
    open: boolean
  }) =>
    open ? (
      <button
        onClick={() => {
          onSelect({ model: 'model-x', provider: 'acme' })
          onOpenChange(false)
        }}
        type="button"
      >
        pick-model:{currentModel || 'none'}
      </button>
    ) : null
}))

beforeEach(() => {
  resetTeamConfig()
  setTeamLogOpen(true)
  $teamMembers.set([])
  $teamRun.set(null)
  $gatewayState.set('open')
  controller.startTeamRun.mockClear()
  controller.startTeamRun.mockResolvedValue(true)
  controller.stopTeamRun.mockClear()
  controller.resetTeam.mockClear()
  controller.submitTeamPrompt.mockClear()
  controller.submitTeamPrompt.mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  $gatewayState.set('idle')
  $sessionStates.set({})
})

const memberPanes = () => document.querySelectorAll('[data-slot="team-member"]')
const finalPane = () => document.querySelector('[data-slot="team-final"]')

function seedDoneRunWith(finalStatus: 'idle' | 'synthesizing' = 'idle') {
  setTeamMemberModel(0, { model: 'lead-model', provider: 'p' })

  act(() => {
    $teamMembers.set([
      { ...createTeamMember(0, 'lead-model', 'p'), runtimeId: 'rt-0', status: 'idle', storedSessionId: 's-0' },
      { ...createTeamMember(1, '', ''), runtimeId: 'rt-1', status: 'idle', storedSessionId: 's-1' },
      {
        ...createTeamMember(TEAM_FINAL_INDEX, 'lead-model', 'p'),
        runtimeId: 'rt-final',
        status: finalStatus,
        storedSessionId: 's-final'
      }
    ])
    $teamRun.set({
      ...createTeamRun('Build it', 4),
      endedAt: Date.now(),
      final: 'The outcome.',
      round: 2,
      status: finalStatus === 'synthesizing' ? 'running' : 'done'
    })
  })
}

describe('TeamPage before a run', () => {
  it('explains the loop, shows three seats by default and keeps Start off until there is a goal', () => {
    render(<TeamPage />)

    expect(screen.getByText(/The lead works the goal/)).toBeTruthy()
    expect(memberPanes()).toHaveLength(3)
    expect(screen.getByText('Lead')).toBeTruthy()
    expect(screen.getByText('Reviewer 2')).toBeTruthy()
    expect(screen.getByText('Reviewer 3')).toBeTruthy()
    // The Final-outcome pane is always there, under the seats, and says what
    // it is for until the run ends. It is not one of the working seats.
    expect(finalPane()).toBeTruthy()
    expect(finalPane()!.textContent).toContain('Final outcome')
    expect(finalPane()!.textContent).toContain('final outcome lands here when the run ends')
    expect(finalPane()!.querySelector('button')).toBeNull()

    const start = screen.getByRole('button', { name: /Start team/ }) as HTMLButtonElement
    expect(start.disabled).toBe(true)

    fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Ship it' } })
    expect(start.disabled).toBe(false)
  })

  it('says so when Robo is not connected, and never starts', () => {
    act(() => $gatewayState.set('closed'))
    render(<TeamPage />)

    expect(screen.getByText('Robo is not connected.')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Goal'), { target: { value: 'Ship it' } })
    expect((screen.getByRole('button', { name: /Start team/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('has no round cap by default and says so', () => {
    render(<TeamPage />)

    expect($teamConfig.get().maxRounds).toBe(0)
    // The rounds control reads "Unlimited" (Radix keeps the selected item's
    // text available while the list is closed).
    expect(screen.getByRole('combobox', { name: 'Rounds' }).textContent).toContain('Unlimited')
  })

  it('counts rounds without a cap in the status line when the run is unlimited', () => {
    act(() => {
      $teamMembers.set([
        { ...createTeamMember(0, 'lead-model', 'p'), runtimeId: 'rt-0', status: 'working', storedSessionId: 's-0' }
      ])
      $teamRun.set({ ...createTeamRun('Build it', 0), round: 7, status: 'running' })
    })

    render(<TeamPage />)
    expect(screen.getByText('Round 7')).toBeTruthy()
    expect(screen.queryByText(/Round 7 of/)).toBeNull()
  })

  it('changes the seat count from the members control and remembers it', () => {
    render(<TeamPage />)

    fireEvent.click(screen.getByRole('button', { name: '4' }))
    expect(memberPanes()).toHaveLength(4)
    expect($teamConfig.get().size).toBe(4)

    fireEvent.click(screen.getByRole('button', { name: '2' }))
    expect(memberPanes()).toHaveLength(2)
  })

  it('picks a model per seat through the model picker', () => {
    render(<TeamPage />)

    // Every seat starts on the profile default.
    expect(screen.getAllByText('Profile default')).toHaveLength(3)

    fireEvent.click(screen.getAllByText('Profile default')[1])
    fireEvent.click(screen.getByText('pick-model:none'))

    expect($teamConfig.get().members[1]).toEqual({ model: 'model-x', provider: 'acme' })
    expect(screen.getByText('model-x')).toBeTruthy()
    expect(screen.queryByText(/pick-model/)).toBeNull()
  })

  it('starts the run with the typed goal on Enter and on the button, clearing the box each time', () => {
    render(<TeamPage />)
    const goal = screen.getByLabelText('Goal') as HTMLTextAreaElement

    fireEvent.change(goal, { target: { value: 'Write the docs' } })
    fireEvent.keyDown(goal, { key: 'Enter' })
    expect(controller.startTeamRun).toHaveBeenCalledWith('Write the docs')
    // Like a chat composer: the box clears the moment the goal is sent.
    expect(goal.value).toBe('')

    fireEvent.change(goal, { target: { value: 'Second goal' } })
    fireEvent.keyDown(goal, { key: 'Enter', shiftKey: true })
    expect(controller.startTeamRun).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: /Start team/ }))
    expect(controller.startTeamRun).toHaveBeenCalledTimes(2)
    expect(controller.startTeamRun).toHaveBeenLastCalledWith('Second goal')
    expect(goal.value).toBe('')
  })

  it('hands the goal back when the start never became a run', async () => {
    controller.startTeamRun.mockResolvedValue(false)
    render(<TeamPage />)
    const goal = screen.getByLabelText('Goal') as HTMLTextAreaElement

    fireEvent.change(goal, { target: { value: 'Write the docs' } })
    fireEvent.keyDown(goal, { key: 'Enter' })
    expect(goal.value).toBe('')

    await waitFor(() => expect(goal.value).toBe('Write the docs'))
  })
})

describe('TeamPage during and after a run', () => {
  function seedRun() {
    setTeamMemberModel(0, { model: 'lead-model', provider: 'p' })
    const run = createTeamRun('Build it', 4)

    act(() => {
      $teamMembers.set([
        { ...createTeamMember(0, 'lead-model', 'p'), runtimeId: 'rt-0', status: 'working', storedSessionId: 's-0' },
        { ...createTeamMember(1, '', ''), runtimeId: 'rt-1', status: 'reviewing', storedSessionId: 's-1' },
        { ...createTeamMember(2, '', ''), status: 'creating' }
      ])
      $teamRun.set({ ...run, round: 2, status: 'running' })
    })

    return run
  }

  it('shows Stop, the round, locks the seats and mounts the bound members’ chats', () => {
    seedRun()
    render(<TeamPage />)

    expect(screen.getByText('Round 2 of 4')).toBeTruthy()
    // The goal box is empty during a run; the goal itself stays readable in
    // the status line and at the top of the log.
    expect(document.querySelector('[data-slot="team-run-goal"]')!.textContent).toBe('Build it')
    expect(document.querySelector('[data-slot="team-log-goal"]')!.textContent).toContain('Build it')
    expect(screen.getByRole('button', { name: /Stop/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Start team/ })).toBeNull()
    expect(screen.getAllByTestId('tile-chat').map(node => node.textContent)).toEqual(['rt-0', 'rt-1'])
    expect(screen.getByText('Opening the session…')).toBeTruthy()
    expect(screen.getByText('Working')).toBeTruthy()
    expect(screen.getByText('Reviewing')).toBeTruthy()

    const modelButton = screen.getByText('lead-model').closest('button') as HTMLButtonElement
    expect(modelButton.disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: /Stop/ }))
    expect(controller.stopTeamRun).toHaveBeenCalledTimes(1)
  })

  it('says why a selected seat cannot be messaged yet instead of "start the team" mid-run', () => {
    seedRun()
    render(<TeamPage />)

    // Seat 3 is still opening: selecting its pane disables the bar with the
    // seat's own reason.
    fireEvent.click(document.querySelector('[data-member-index="2"]')!)

    const input = screen.getByLabelText('Message a member') as HTMLTextAreaElement
    expect(input.disabled).toBe(true)
    expect(input.getAttribute('placeholder')).toBe('Opening the session…')

    fireEvent.click(document.querySelector('[data-member-index="0"]')!)
    expect(input.disabled).toBe(false)
    expect(input.getAttribute('placeholder')).toBe('Message Lead…')
  })

  it('says when a member is waiting on the user, whatever the controller thinks it is doing', () => {
    seedRun()
    render(<TeamPage />)
    expect(screen.getByText('Working')).toBeTruthy()

    act(() => {
      $sessionStates.set({ 'rt-0': { ...createClientSessionState('s-0'), busy: true, needsInput: true } })
    })

    expect(screen.queryByText('Working')).toBeNull()
    expect(screen.getByText('Needs you')).toBeTruthy()
  })

  it('shows a seat the user is talking to as Working, whatever the controller thinks', () => {
    seedDoneRunWith('idle')
    render(<TeamPage />)
    expect(screen.queryByText('Working')).toBeNull()

    // The user asked the Final something: its session is busy answering.
    act(() => {
      $sessionStates.set({ 'rt-final': { ...createClientSessionState('s-final'), busy: true } })
    })

    expect(finalPane()!.getAttribute('data-member-status')).toBe('working')
    expect(screen.getByText('Working')).toBeTruthy()
  })

  it('writes the log as the run goes and shows the final answer with a copy action', () => {
    const run = seedRun()
    render(<TeamPage />)

    act(() => {
      appendTeamLog(run.id, { kind: 'round', round: 1, text: '' })
      appendTeamLog(run.id, { detail: 'B is tested.', kind: 'vote', memberIndex: 1, round: 1, text: 'B > A' })
      appendTeamLog(run.id, { code: 'borda', detail: 'A: x\nB: y', kind: 'decision', round: 1, text: 'B: y' })
      appendTeamLog(run.id, { code: 'sideTaskAssigned', kind: 'side', memberIndex: 2, round: 1, text: 'Bench' })
    })

    expect(screen.getByText('Round 1')).toBeTruthy()
    expect(screen.getByText('Reviewer 2 ranked B > A')).toBeTruthy()
    expect(screen.getByText('B is tested.')).toBeTruthy()
    expect(screen.getByText('Team chose B: y — ranked vote')).toBeTruthy()
    expect(screen.getByText('Side task → Reviewer 3')).toBeTruthy()

    act(() => {
      // The controller logs the outcome as a `final` line AND sets run.final.
      appendTeamLog(run.id, { kind: 'final', round: 1, text: 'Here is the answer.' })
      $teamRun.set({ ...$teamRun.get()!, endedAt: Date.now(), final: 'Here is the answer.', status: 'done' })
    })

    expect(screen.getByText('Done')).toBeTruthy()
    // The log line marks the moment; the text itself is shown once — in the
    // answer box with its copy action, not again as that line's body.
    expect(document.querySelector('[data-log-kind="final"]')!.textContent).toBe('Final answer')
    expect(screen.getAllByText('Here is the answer.')).toHaveLength(1)

    const answerBox = document.querySelector('[data-slot="team-final-answer"]')!
    expect(answerBox.textContent).toContain('Final answer')
    expect(answerBox.textContent).toContain('Here is the answer.')
    expect(screen.getByRole('button', { name: /Copy/ })).toBeTruthy()
    // The run is over: Start is back and the seats unlock.
    expect(screen.getByRole('button', { name: /Start team/ })).toBeTruthy()
    expect((screen.getByText('lead-model').closest('button') as HTMLButtonElement).disabled).toBe(false)
  })

  it('surfaces a failed run’s reason and hides the log rail on request', () => {
    const run = seedRun()
    render(<TeamPage />)

    act(() => {
      appendTeamLog(run.id, { detail: 'Provider down', kind: 'error', memberIndex: 0, round: 1, text: '' })
      $teamRun.set({ ...$teamRun.get()!, error: 'Provider down', status: 'failed' })
    })

    expect(screen.getByText('Failed')).toBeTruthy()
    expect(screen.getByText('Lead failed')).toBeTruthy()
    expect(document.querySelector('[data-slot="team-log-rail"]')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Hide log/ }))
    expect(document.querySelector('[data-slot="team-log-rail"]')).toBeNull()
    expect(screen.getByRole('button', { name: /Show log/ })).toBeTruthy()
  })

  it('asks before starting a new team, then resets', () => {
    seedRun()
    act(() => {
      $teamRun.set({ ...$teamRun.get()!, status: 'done' })
    })
    render(<TeamPage />)

    fireEvent.click(screen.getByRole('button', { name: /New team/ }))
    expect(screen.getByText('Start a new team?')).toBeTruthy()
    expect(controller.resetTeam).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Start new team' }))
    expect(controller.resetTeam).toHaveBeenCalledTimes(1)
  })
})

describe('TeamPage layout and the single composer', () => {
  it('shows exactly one composer — never one per pane — and only once a member is live', () => {
    // Before a run there is no crew, so no composer.
    const { unmount } = render(<TeamPage />)
    expect(document.querySelectorAll('[data-slot="team-composer-input"]')).toHaveLength(0)
    unmount()

    act(() => {
      $teamMembers.set([
        { ...createTeamMember(0, 'lead-model', 'p'), runtimeId: 'rt-0', status: 'working', storedSessionId: 's-0' },
        { ...createTeamMember(1, '', ''), runtimeId: 'rt-1', status: 'idle', storedSessionId: 's-1' },
        { ...createTeamMember(2, '', ''), status: 'creating' }
      ])
      $teamRun.set({ ...createTeamRun('Build it', 4), round: 1, status: 'running' })
    })

    render(<TeamPage />)
    // One composer for the whole team, regardless of how many panes are up.
    expect(document.querySelectorAll('[data-slot="team-composer-input"]')).toHaveLength(1)
    // The two bound members get a chip; the still-creating seat does not.
    expect(screen.getByRole('button', { name: 'Lead' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Reviewer 2' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Reviewer 3' })).toBeNull()
  })

  it('sends a message to the pane you select through the team submit, which paints it in the pane', async () => {
    act(() => {
      $teamMembers.set([
        { ...createTeamMember(0, 'lead-model', 'p'), runtimeId: 'rt-0', status: 'working', storedSessionId: 's-0' },
        { ...createTeamMember(1, '', ''), runtimeId: 'rt-1', status: 'idle', storedSessionId: 's-1' }
      ])
      $teamRun.set({ ...createTeamRun('Build it', 4), round: 1, status: 'running' })
    })
    render(<TeamPage />)

    const input = screen.getByLabelText('Message a member')

    // Defaults to the lead.
    fireEvent.change(input, { target: { value: 'focus on correctness' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(controller.submitTeamPrompt).toHaveBeenCalledWith('rt-0', 'focus on correctness'))
    // Sent: the box is empty again.
    await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe(''))

    // Select Reviewer 2's pane; the composer now targets it.
    fireEvent.click(document.querySelector('[data-member-index="1"]')!)
    fireEvent.change(input, { target: { value: 'second opinion?' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(controller.submitTeamPrompt).toHaveBeenCalledWith('rt-1', 'second opinion?'))
  })

  it('keeps the text and reports it when the send fails', async () => {
    controller.submitTeamPrompt.mockRejectedValueOnce(new Error('offline'))

    act(() => {
      $teamMembers.set([
        { ...createTeamMember(0, 'lead-model', 'p'), runtimeId: 'rt-0', status: 'idle', storedSessionId: 's-0' }
      ])
      $teamRun.set({ ...createTeamRun('Build it', 4), round: 1, status: 'running' })
    })
    render(<TeamPage />)

    const input = screen.getByLabelText('Message a member') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: 'keep me' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(controller.submitTeamPrompt).toHaveBeenCalledWith('rt-0', 'keep me'))
    expect(input.value).toBe('keep me')
  })
})

describe('TeamPage and the Final outcome', () => {
  const seedDoneRun = seedDoneRunWith

  it('mounts the Final seat’s chat full width under the seats, with a star header and no model pick', () => {
    seedDoneRun()
    render(<TeamPage />)

    const pane = finalPane()!
    expect(pane.getAttribute('data-member-index')).toBe(String(TEAM_FINAL_INDEX))
    expect(pane.textContent).toContain('Final outcome')
    expect(pane.textContent).toContain('On the lead’s model')
    // Its transcript is the real tile; the seat count is unchanged.
    expect(screen.getAllByTestId('tile-chat').map(node => node.textContent)).toEqual(['rt-0', 'rt-1', 'rt-final'])
    expect(memberPanes()).toHaveLength(3)
    // Only the lead's model button exists; the Final has nothing to pick.
    expect(screen.getByText('lead-model').closest('button')).toBeTruthy()
    expect(pane.querySelector('button')).toBeNull()
  })

  it('shows the Final seat writing the outcome while the run is still on', () => {
    seedDoneRun('synthesizing')
    render(<TeamPage />)

    expect(finalPane()!.getAttribute('data-member-status')).toBe('synthesizing')
    expect(finalPane()!.textContent).toContain('Writing the outcome')
    expect(screen.queryByText(/final outcome is in/)).toBeNull()
  })

  it('offers the Final outcome as a composer target once the run is done and routes messages to it', async () => {
    seedDoneRun()
    render(<TeamPage />)

    expect(screen.getByText(/final outcome is in/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Final outcome' })).toBeTruthy()

    // Clicking the pane selects it, like any seat; the composer follows.
    fireEvent.click(finalPane()!)
    expect(finalPane()!.getAttribute('data-member-selected')).toBe('true')
    const input = screen.getByLabelText('Message a member') as HTMLTextAreaElement
    expect(input.getAttribute('placeholder')).toBe('Message Final outcome…')

    fireEvent.change(input, { target: { value: 'why that choice?' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(controller.submitTeamPrompt).toHaveBeenCalledWith('rt-final', 'why that choice?'))
    await waitFor(() => expect(input.value).toBe(''))

    // And the chip works the same way.
    fireEvent.click(screen.getByRole('button', { name: 'Lead' }))
    expect(finalPane()!.getAttribute('data-member-selected')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Final outcome' }))
    expect(finalPane()!.getAttribute('data-member-selected')).toBe('true')
  })

  it('keeps the Final selected when the seat count changes', () => {
    seedDoneRun()
    render(<TeamPage />)

    fireEvent.click(finalPane()!)
    fireEvent.click(screen.getByRole('button', { name: '2' }))
    expect(finalPane()!.getAttribute('data-member-selected')).toBe('true')
    expect(memberPanes()).toHaveLength(2)
  })
})
