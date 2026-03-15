import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ThingCard } from '../components/ThingCard'

const snoozeThing = vi.fn()

const thingTypes: { name: string; icon: string }[] = []

vi.mock('../store', () => ({
  useStore: (selector: (s: { snoozeThing: typeof snoozeThing; things: typeof things; thingTypes: typeof thingTypes }) => unknown) =>
    selector({ snoozeThing, things, thingTypes }),
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

const things = [
  baseThing,
  {
    id: 't2',
    title: 'Sub-task A',
    type_hint: 'task' as const,
    parent_id: 't1',
    checkin_date: null,
    priority: 3,
    active: true,
    surface: true,
    data: null,
    created_at: '2026-01-02T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: null,
    completed_count: null,
  },
]

beforeEach(() => {
  snoozeThing.mockReset()
  snoozeThing.mockResolvedValue(undefined)
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
    const dateArg = snoozeThing.mock.calls[0][1] as string
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
    const dateArg = snoozeThing.mock.calls[0][1] as string
    const passed = new Date(dateArg)
    const nextWeek = new Date()
    nextWeek.setDate(nextWeek.getDate() + 7)
    expect(passed.getDate()).toBe(nextWeek.getDate())
  })

  it('does not show details by default', () => {
    render(<ThingCard thing={baseThing} />)
    expect(screen.queryByText(/Critical/)).not.toBeInTheDocument()
  })

  it('expands to show priority and timestamps on click', () => {
    render(<ThingCard thing={baseThing} />)
    fireEvent.click(screen.getByRole('button', { name: /Finish report/ }))
    expect(screen.getByText('🔴 Critical')).toBeInTheDocument()
    expect(screen.getByText(/Created/)).toBeInTheDocument()
  })

  it('shows data entries when expanded', () => {
    const thingWithData = { ...baseThing, data: { birthday: '1990-05-20', notes: 'Important' } }
    render(<ThingCard thing={thingWithData} />)
    fireEvent.click(screen.getByRole('button', { name: /Finish report/ }))
    expect(screen.getByText('birthday:')).toBeInTheDocument()
    expect(screen.getByText('1990-05-20')).toBeInTheDocument()
    expect(screen.getByText('notes:')).toBeInTheDocument()
    expect(screen.getByText('Important')).toBeInTheDocument()
  })

  it('shows children when expanded', () => {
    render(<ThingCard thing={baseThing} />)
    fireEvent.click(screen.getByRole('button', { name: /Finish report/ }))
    expect(screen.getByText(/Sub-task A/)).toBeInTheDocument()
  })

  it('shows parent when expanded', () => {
    render(<ThingCard thing={things[1]} />)
    fireEvent.click(screen.getByRole('button', { name: /Sub-task A/ }))
    expect(screen.getByText(/Finish report/)).toBeInTheDocument()
  })

  it('collapses on second click', () => {
    render(<ThingCard thing={baseThing} />)
    const row = screen.getByRole('button', { name: /Finish report/ })
    fireEvent.click(row)
    expect(screen.getByText('🔴 Critical')).toBeInTheDocument()
    fireEvent.click(row)
    expect(screen.queryByText('🔴 Critical')).not.toBeInTheDocument()
  })
})
