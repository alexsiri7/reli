import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DueTodayRow, TodayEventRow } from '../components/BriefingPanel'
import type { BriefingItem, CalendarEvent } from '../store'

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
    render(<DueTodayRow item={mockItem} onDone={vi.fn()} onSnooze={vi.fn()} onChat={vi.fn()} />)
    expect(screen.getByText('Write proposal')).toBeInTheDocument()
    expect(screen.getByText('Due today')).toBeInTheDocument()
  })

  it('calls onDone with thing id when Done clicked', () => {
    const onDone = vi.fn()
    render(<DueTodayRow item={mockItem} onDone={onDone} onSnooze={vi.fn()} onChat={vi.fn()} />)
    fireEvent.click(screen.getByText('Done'))
    expect(onDone).toHaveBeenCalledWith('thing-1')
  })

  it('calls onSnooze with thing id when Snooze clicked', () => {
    const onSnooze = vi.fn()
    render(<DueTodayRow item={mockItem} onDone={vi.fn()} onSnooze={onSnooze} onChat={vi.fn()} />)
    fireEvent.click(screen.getByText('Snooze'))
    expect(onSnooze).toHaveBeenCalledWith('thing-1')
  })

  it('calls onChat with thing id and title when Chat clicked', () => {
    const onChat = vi.fn()
    render(<DueTodayRow item={mockItem} onDone={vi.fn()} onSnooze={vi.fn()} onChat={onChat} />)
    fireEvent.click(screen.getByText('Chat'))
    expect(onChat).toHaveBeenCalledWith('thing-1', 'Write proposal')
  })

  it('renders without reason when reasons array is empty', () => {
    const itemNoReasons: BriefingItem = { ...mockItem, reasons: [] }
    render(<DueTodayRow item={itemNoReasons} onDone={vi.fn()} onSnooze={vi.fn()} onChat={vi.fn()} />)
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
