import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ThingCard } from '../components/ThingCard'

const snoozeThing = vi.fn()
const openThingDetail = vi.fn()

const thingTypes: { name: string; icon: string }[] = []

vi.mock('../store', () => ({
  useStore: (selector: (s: { snoozeThing: typeof snoozeThing; thingTypes: typeof thingTypes; openThingDetail: typeof openThingDetail }) => unknown) =>
    selector({ snoozeThing, thingTypes, openThingDetail }),
}))

const baseThing = {
  id: 't1',
  title: 'Finish report',
  type_hint: 'task' as const,
  parent_id: null,
  checkin_date: null,
  priority: 1,
  active: true,
  surface: true,
  data: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  last_referenced: null,
  open_questions: null,
  children_count: null,
  completed_count: null,
}

beforeEach(() => {
  snoozeThing.mockReset()
  snoozeThing.mockResolvedValue(undefined)
  openThingDetail.mockReset()
})

describe('ThingCard', () => {
  it('renders title', () => {
    render(<ThingCard thing={baseThing} />)
    expect(screen.getByText('Finish report')).toBeInTheDocument()
  })

  it('renders type_hint icon', () => {
    render(<ThingCard thing={baseThing} />)
    expect(screen.getByTitle('task')).toBeInTheDocument()
  })

  it('renders checkin_date label when set', () => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    render(<ThingCard thing={{ ...baseThing, checkin_date: tomorrow.toISOString() }} />)
    expect(screen.getByText('Tomorrow')).toBeInTheDocument()
  })

  it('shows snooze popover with options on click', () => {
    render(<ThingCard thing={baseThing} />)
    const snoozeBtn = screen.getByTitle('Snooze')
    fireEvent.click(snoozeBtn)
    expect(screen.getByText('Tomorrow')).toBeInTheDocument()
    expect(screen.getByText('Next week')).toBeInTheDocument()
  })

  it('calls snoozeThing with tomorrow date', () => {
    render(<ThingCard thing={baseThing} />)
    fireEvent.click(screen.getByTitle('Snooze'))
    fireEvent.click(screen.getByText('Tomorrow'))

    expect(snoozeThing).toHaveBeenCalledWith('t1', expect.any(String))
    const dateArg = snoozeThing.mock.calls[0]![1] as string
    const passed = new Date(dateArg)
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    expect(passed.getDate()).toBe(tomorrow.getDate())
  })

  it('calls snoozeThing with next-week date', () => {
    render(<ThingCard thing={baseThing} />)
    fireEvent.click(screen.getByTitle('Snooze'))
    fireEvent.click(screen.getByText('Next week'))

    expect(snoozeThing).toHaveBeenCalledWith('t1', expect.any(String))
    const dateArg = snoozeThing.mock.calls[0]![1] as string
    const passed = new Date(dateArg)
    const nextWeek = new Date()
    nextWeek.setDate(nextWeek.getDate() + 7)
    expect(passed.getDate()).toBe(nextWeek.getDate())
  })

  it('does not show inline details (detail panel handles this)', () => {
    render(<ThingCard thing={baseThing} />)
    expect(screen.queryByText(/Critical/)).not.toBeInTheDocument()
  })

  it('calls openThingDetail on click', () => {
    render(<ThingCard thing={baseThing} />)
    fireEvent.click(screen.getByRole('button', { name: /Finish report/ }))
    expect(openThingDetail).toHaveBeenCalledWith('t1')
  })

  it('does not call openThingDetail when snooze is clicked', () => {
    render(<ThingCard thing={baseThing} />)
    fireEvent.click(screen.getByTitle('Snooze'))
    expect(openThingDetail).not.toHaveBeenCalled()
  })

  it('shows project progress bar', () => {
    const project = { ...baseThing, type_hint: 'project' as const, children_count: 5, completed_count: 3 }
    render(<ThingCard thing={project} />)
    expect(screen.getByText('3/5')).toBeInTheDocument()
  })

  it('shows overdue indicator', () => {
    const pastDate = new Date()
    pastDate.setDate(pastDate.getDate() - 3)
    render(<ThingCard thing={{ ...baseThing, checkin_date: pastDate.toISOString() }} />)
    expect(screen.getByText(/overdue/)).toBeInTheDocument()
  })
})
