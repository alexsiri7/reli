import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Nudge } from '../store'

const mockDismissNudge = vi.fn()
const mockStopNudgeType = vi.fn()
const mockOpenThingDetail = vi.fn()

vi.mock('../store', () => ({
  useStore: Object.assign(
    vi.fn(),
    {
      getState: vi.fn(() => ({
        dismissNudge: mockDismissNudge,
        stopNudgeType: mockStopNudgeType,
        openThingDetail: mockOpenThingDetail,
      })),
    }
  ),
}))

import { NudgeBanner } from '../components/NudgeBanner'

const baseMockNudge: Nudge = {
  id: 'proactive_abc123_birthday',
  nudge_type: 'approaching_date',
  message: "Mom's birthday is in 3 days",
  thing_id: 'abc123',
  thing_title: 'Mom',
  thing_type_hint: 'person',
  days_away: 3,
  primary_action_label: 'View Details',
}

beforeEach(() => {
  mockDismissNudge.mockClear()
  mockStopNudgeType.mockClear()
  mockOpenThingDetail.mockClear()
})

describe('NudgeBanner', () => {
  it('renders nudge message text', () => {
    render(<NudgeBanner nudge={baseMockNudge} />)
    expect(screen.getByText("Mom's birthday is in 3 days")).toBeInTheDocument()
  })

  it('calls dismissNudge when "Got it" is clicked', async () => {
    render(<NudgeBanner nudge={baseMockNudge} />)
    await userEvent.click(screen.getByText('Got it'))
    expect(mockDismissNudge).toHaveBeenCalledWith('proactive_abc123_birthday')
  })

  it('calls stopNudgeType when "Stop these" is clicked', async () => {
    render(<NudgeBanner nudge={baseMockNudge} />)
    await userEvent.click(screen.getByText('Stop these'))
    expect(mockStopNudgeType).toHaveBeenCalledWith('proactive_abc123_birthday')
  })

  it('renders primary action button when primary_action_label and thing_id are set', () => {
    render(<NudgeBanner nudge={baseMockNudge} />)
    expect(screen.getByText('View Details')).toBeInTheDocument()
  })

  it('does not render primary action button when primary_action_label is null', () => {
    const nudge: Nudge = { ...baseMockNudge, primary_action_label: null }
    render(<NudgeBanner nudge={nudge} />)
    expect(screen.queryByText('View Details')).not.toBeInTheDocument()
  })

  it('does not render primary action button when thing_id is null', () => {
    const nudge: Nudge = { ...baseMockNudge, thing_id: null }
    render(<NudgeBanner nudge={nudge} />)
    expect(screen.queryByText('View Details')).not.toBeInTheDocument()
  })

  it('renders thing type icon when thing_type_hint is set', () => {
    render(<NudgeBanner nudge={baseMockNudge} />)
    // typeIcon('person') returns the person emoji
    const messageEl = screen.getByText("Mom's birthday is in 3 days")
    expect(messageEl.parentElement?.textContent).toContain("Mom's birthday is in 3 days")
  })

  it('does not crash when thing_type_hint is null', () => {
    const nudge: Nudge = { ...baseMockNudge, thing_type_hint: null }
    render(<NudgeBanner nudge={nudge} />)
    expect(screen.getByText("Mom's birthday is in 3 days")).toBeInTheDocument()
  })
})
