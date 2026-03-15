import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CalendarSection } from '../components/CalendarSection'
import type { CalendarEvent, CalendarStatus } from '../store'

const fetchCalendarStatus = vi.fn()
const fetchCalendarEvents = vi.fn()
const connectCalendar = vi.fn()
const disconnectCalendar = vi.fn()

let storeState: Record<string, unknown> = {}

vi.mock('../store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) => selector(storeState),
}))

vi.mock('zustand/react/shallow', () => ({
  useShallow: (fn: unknown) => fn,
}))

const makeEvent = (overrides: Partial<CalendarEvent> = {}): CalendarEvent => ({
  id: 'e1',
  summary: 'Team standup',
  start: new Date().toISOString(),
  end: new Date().toISOString(),
  all_day: false,
  location: null,
  status: 'confirmed',
  ...overrides,
})

beforeEach(() => {
  fetchCalendarStatus.mockReset()
  fetchCalendarEvents.mockReset()
  connectCalendar.mockReset()
  disconnectCalendar.mockReset()

  storeState = {
    calendarStatus: { configured: true, connected: true } as CalendarStatus,
    calendarEvents: [] as CalendarEvent[],
    fetchCalendarStatus,
    fetchCalendarEvents,
    connectCalendar,
    disconnectCalendar,
  }
})

describe('CalendarSection', () => {
  it('renders nothing when not configured', () => {
    storeState.calendarStatus = { configured: false, connected: false }
    const { container } = render(<CalendarSection />)
    expect(container.innerHTML).toBe('')
  })

  it('shows connect button when configured but not connected', () => {
    storeState.calendarStatus = { configured: true, connected: false }
    render(<CalendarSection />)
    expect(screen.getByText('Connect Google Calendar')).toBeInTheDocument()
  })

  it('calls connectCalendar on connect button click', () => {
    storeState.calendarStatus = { configured: true, connected: false }
    render(<CalendarSection />)
    fireEvent.click(screen.getByText('Connect Google Calendar'))
    expect(connectCalendar).toHaveBeenCalled()
  })

  it('shows "No upcoming events" when connected with no events', () => {
    render(<CalendarSection />)
    expect(screen.getByText('No upcoming events')).toBeInTheDocument()
  })

  it('renders events when connected', () => {
    storeState.calendarEvents = [makeEvent({ summary: 'Team standup' })]
    render(<CalendarSection />)
    expect(screen.getByText('Team standup')).toBeInTheDocument()
  })

  it('renders event location when present', () => {
    storeState.calendarEvents = [makeEvent({ location: 'Room 42' })]
    render(<CalendarSection />)
    expect(screen.getByText('Room 42')).toBeInTheDocument()
  })

  it('shows "All day" for all-day events', () => {
    storeState.calendarEvents = [makeEvent({ all_day: true })]
    render(<CalendarSection />)
    expect(screen.getByText('All day')).toBeInTheDocument()
  })

  it('shows disconnect button when connected', () => {
    render(<CalendarSection />)
    expect(screen.getByText('Disconnect')).toBeInTheDocument()
  })

  it('calls disconnectCalendar on disconnect click', () => {
    render(<CalendarSection />)
    fireEvent.click(screen.getByText('Disconnect'))
    expect(disconnectCalendar).toHaveBeenCalled()
  })

  it('fetches calendar status on mount', () => {
    render(<CalendarSection />)
    expect(fetchCalendarStatus).toHaveBeenCalled()
  })

  it('fetches events when connected', () => {
    render(<CalendarSection />)
    expect(fetchCalendarEvents).toHaveBeenCalled()
  })

  it('groups events by date label', () => {
    const today = new Date()
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)

    storeState.calendarEvents = [
      makeEvent({ id: 'e1', summary: 'Morning sync', start: today.toISOString() }),
      makeEvent({ id: 'e2', summary: 'Planning', start: tomorrow.toISOString() }),
    ]
    render(<CalendarSection />)
    expect(screen.getByText('Today')).toBeInTheDocument()
    expect(screen.getByText('Tomorrow')).toBeInTheDocument()
  })
})
