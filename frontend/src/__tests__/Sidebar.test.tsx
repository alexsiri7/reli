import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Sidebar } from '../components/Sidebar'

type Thing = {
  id: string
  title: string
  type_hint: string | null
  parent_id: string | null
  checkin_date: string | null
  priority: number
  active: boolean
  data: null
  created_at: string
  updated_at: string
}

let mockState = {
  things: [] as Thing[],
  briefing: [] as Thing[],
  loading: false,
  snoozeThing: vi.fn(),
}

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}))

const makeThing = (overrides: Partial<Thing> = {}): Thing => ({
  id: 't1',
  title: 'Test Thing',
  type_hint: 'task',
  parent_id: null,
  checkin_date: null,
  priority: 2,
  active: true,
  data: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('Sidebar', () => {
  it('shows empty state when no things', () => {
    mockState = { things: [], briefing: [], loading: false, snoozeThing: vi.fn() }
    render(<Sidebar />)
    expect(screen.getByText('Start by typing in the chat…')).toBeInTheDocument()
  })

  it('renders Things list', () => {
    mockState = {
      things: [makeThing({ title: 'Buy groceries' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
    }
    render(<Sidebar />)
    expect(screen.getByText('Buy groceries')).toBeInTheDocument()
  })

  it('shows loading skeleton when loading with no things', () => {
    mockState = { things: [], briefing: [], loading: true, snoozeThing: vi.fn() }
    const { container } = render(<Sidebar />)
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument()
  })

  it('shows Daily Briefing section when briefing has items', () => {
    const overdueDate = '2026-01-01T00:00:00Z'
    mockState = {
      things: [],
      briefing: [makeThing({ id: 'b1', title: 'Overdue Task', checkin_date: overdueDate })],
      loading: false,
      snoozeThing: vi.fn(),
    }
    render(<Sidebar />)
    expect(screen.getByText('📅 Daily Briefing')).toBeInTheDocument()
    expect(screen.getByText('Overdue Task')).toBeInTheDocument()
  })

  it('shows snooze button on ThingCard', () => {
    mockState = {
      things: [makeThing({ title: 'My Thing' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
    }
    render(<Sidebar />)
    expect(screen.getByTitle('Snooze')).toBeInTheDocument()
  })
})
