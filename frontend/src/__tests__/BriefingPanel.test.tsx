import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DueTodayRow, TodayEventRow, FindingCard } from '../components/BriefingPanel'
import type { BriefingItem, CalendarEvent, SweepFinding, Thing } from '../store'

const mockItem: BriefingItem = {
  thing: { id: 'thing-1', title: 'Write proposal', active: true } as BriefingItem['thing'],
  importance: 1,
  urgency: 0.8,
  score: 0.9,
  reasons: ['Due today'],
}

const makeEvent = (overrides: Partial<CalendarEvent> = {}): CalendarEvent => ({
  id: 'e1',
  summary: 'Team standup',
  start: '2026-04-18T09:30:00Z',
  end: '2026-04-18T10:00:00Z',
  all_day: false,
  location: null,
  status: 'confirmed',
  ...overrides,
})

describe('DueTodayRow', () => {
  it('renders thing title and reason', () => {
    render(<DueTodayRow item={mockItem} onDone={vi.fn()} onSnooze={vi.fn()} onChat={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />)
    expect(screen.getByText('Write proposal')).toBeInTheDocument()
    expect(screen.getByText('Due today')).toBeInTheDocument()
  })

  it('calls onDone with thing id when Done clicked', () => {
    const onDone = vi.fn()
    render(<DueTodayRow item={mockItem} onDone={onDone} onSnooze={vi.fn()} onChat={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />)
    fireEvent.click(screen.getByText('Done'))
    expect(onDone).toHaveBeenCalledWith('thing-1')
  })

  it('calls onSnoozeToggle when Snooze clicked', () => {
    const onSnoozeToggle = vi.fn()
    render(<DueTodayRow item={mockItem} onDone={vi.fn()} onSnooze={vi.fn()} onChat={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={onSnoozeToggle} />)
    fireEvent.click(screen.getByText('Snooze'))
    expect(onSnoozeToggle).toHaveBeenCalled()
  })

  it('calls onChat with thing id and title when Chat clicked', () => {
    const onChat = vi.fn()
    render(<DueTodayRow item={mockItem} onDone={vi.fn()} onSnooze={vi.fn()} onChat={onChat} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />)
    fireEvent.click(screen.getByText('Chat'))
    expect(onChat).toHaveBeenCalledWith('thing-1', 'Write proposal')
  })

  it('calls onSnoozeToggle when clicking outside the open snooze menu', () => {
    const onSnoozeToggle = vi.fn()
    render(
      <DueTodayRow
        item={mockItem}
        onDone={vi.fn()}
        onSnooze={vi.fn()}
        onChat={vi.fn()}
        snoozeMenuOpen={true}
        onSnoozeToggle={onSnoozeToggle}
      />
    )
    // Simulate mousedown on document body (outside the snooze menu)
    fireEvent.mouseDown(document.body)
    expect(onSnoozeToggle).toHaveBeenCalled()
  })

  it('renders without reason when reasons array is empty', () => {
    const itemNoReasons: BriefingItem = { ...mockItem, reasons: [] }
    render(<DueTodayRow item={itemNoReasons} onDone={vi.fn()} onSnooze={vi.fn()} onChat={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />)
    expect(screen.getByText('Write proposal')).toBeInTheDocument()
  })
})

describe('TodayEventRow', () => {
  it('renders event summary', () => {
    render(<TodayEventRow event={makeEvent()} />)
    expect(screen.getByText('Team standup')).toBeInTheDocument()
  })

  it('shows "All day" for all-day events', () => {
    render(<TodayEventRow event={makeEvent({ all_day: true })} />)
    expect(screen.getByText('All day')).toBeInTheDocument()
  })

  it('renders location when present', () => {
    render(<TodayEventRow event={makeEvent({ location: 'Room 3B' })} />)
    expect(screen.getByText('Room 3B')).toBeInTheDocument()
  })

  it('omits location when null', () => {
    render(<TodayEventRow event={makeEvent({ location: null })} />)
    expect(screen.queryByText('Room 3B')).not.toBeInTheDocument()
  })

  it('falls back to raw string for malformed date', () => {
    render(<TodayEventRow event={makeEvent({ start: 'not-a-date', all_day: false })} />)
    expect(screen.getByText('not-a-date')).toBeInTheDocument()
  })
})

const mockFinding: SweepFinding = {
  id: 'finding-1',
  finding_type: 'stale',
  message: 'No activity in 30 days',
  thing_id: 'thing-3',
  thing: { id: 'thing-3', title: 'Schedule team retrospective' } as Thing,
  dismissed: false,
  snoozed_until: null,
  priority: 1,
  expires_at: null,
  created_at: '2026-03-01T10:00:00Z',
}

describe('FindingCard', () => {
  it('renders col-span-2 when isFirst is true', () => {
    const { container } = render(
      <FindingCard finding={mockFinding} isFirst={true} onDismiss={vi.fn()} onSnooze={vi.fn()} onAct={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />
    )
    expect(container.firstChild).toHaveClass('col-span-2')
  })

  it('does not render col-span-2 when isFirst is false', () => {
    const { container } = render(
      <FindingCard finding={mockFinding} isFirst={false} onDismiss={vi.fn()} onSnooze={vi.fn()} onAct={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />
    )
    expect(container.firstChild).not.toHaveClass('col-span-2')
  })

  it('renders finding message', () => {
    render(
      <FindingCard finding={mockFinding} isFirst={false} onDismiss={vi.fn()} onSnooze={vi.fn()} onAct={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />
    )
    expect(screen.getByText('No activity in 30 days')).toBeInTheDocument()
  })

  it('renders Open button when thing_id is set', () => {
    render(
      <FindingCard finding={mockFinding} isFirst={false} onDismiss={vi.fn()} onSnooze={vi.fn()} onAct={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />
    )
    expect(screen.getByText('Open')).toBeInTheDocument()
  })

  it('does not render Open button when thing_id is null', () => {
    const noThingFinding = { ...mockFinding, thing_id: null, thing: null }
    render(
      <FindingCard finding={noThingFinding} isFirst={false} onDismiss={vi.fn()} onSnooze={vi.fn()} onAct={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />
    )
    expect(screen.queryByText('Open')).not.toBeInTheDocument()
  })

  it('calls onDismiss with finding id when Dismiss clicked', () => {
    const onDismiss = vi.fn()
    render(
      <FindingCard finding={mockFinding} isFirst={false} onDismiss={onDismiss} onSnooze={vi.fn()} onAct={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />
    )
    fireEvent.click(screen.getByText('Dismiss'))
    expect(onDismiss).toHaveBeenCalledWith('finding-1')
  })

  it('calls onAct with finding when Open clicked', () => {
    const onAct = vi.fn()
    render(
      <FindingCard finding={mockFinding} isFirst={false} onDismiss={vi.fn()} onSnooze={vi.fn()} onAct={onAct} snoozeMenuOpen={false} onSnoozeToggle={vi.fn()} />
    )
    fireEvent.click(screen.getByText('Open'))
    expect(onAct).toHaveBeenCalledWith(mockFinding)
  })

  it('calls onSnoozeToggle when Snooze clicked', () => {
    const onSnoozeToggle = vi.fn()
    render(
      <FindingCard finding={mockFinding} isFirst={false} onDismiss={vi.fn()} onSnooze={vi.fn()} onAct={vi.fn()} snoozeMenuOpen={false} onSnoozeToggle={onSnoozeToggle} />
    )
    fireEvent.click(screen.getByText('Snooze'))
    expect(onSnoozeToggle).toHaveBeenCalled()
  })
})
