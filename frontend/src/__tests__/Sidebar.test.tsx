import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Sidebar } from '../components/Sidebar'

type Thing = {
  id: string
  title: string
  type_hint: string | null
  parent_id: string | null
  checkin_date: string | null
  priority: number
  active: boolean
  surface: boolean
  data: null
  created_at: string
  updated_at: string
  last_referenced: string | null
  open_questions: string[] | null
  children_count: number | null
  completed_count: number | null
}

let mockState: Record<string, unknown> = {
  things: [] as Thing[],
  briefing: [] as Thing[],
  findings: [],
  loading: false,
  snoozeThing: vi.fn(),
  dismissFinding: vi.fn(),
  calendarStatus: { configured: false, connected: false },
  calendarEvents: [],
  fetchCalendarStatus: vi.fn(),
  fetchCalendarEvents: vi.fn(),
  connectCalendar: vi.fn(),
  disconnectCalendar: vi.fn(),
  searchResults: [] as Thing[],
  searchLoading: false,
  searchThings: vi.fn(),
  clearSearch: vi.fn(),
  thingTypes: [],
  proactiveSurfaces: [],
  thingFilterQuery: '',
  thingFilterTypes: [] as string[],
  setThingFilterQuery: vi.fn(),
  toggleThingFilterType: vi.fn(),
  clearThingFilters: vi.fn(),
}

vi.mock('zustand/react/shallow', () => ({
  useShallow: <T,>(fn: (state: unknown) => T) => fn,
}))

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
  surface: true,
  data: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  last_referenced: null,
  open_questions: null,
  children_count: null,
  completed_count: null,
  ...overrides,
})

// Helper to simulate desktop viewport (>=768px)
function setDesktopViewport() {
  Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true })
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === '(min-width: 768px)',
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    onchange: null,
    dispatchEvent: vi.fn(),
  }))
}

// Helper to simulate mobile viewport (<768px)
function setMobileViewport() {
  Object.defineProperty(window, 'innerWidth', { value: 375, writable: true })
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    onchange: null,
    dispatchEvent: vi.fn(),
  }))
}

const searchDefaults = {
  searchResults: [] as Thing[],
  searchLoading: false,
  searchThings: vi.fn(),
  clearSearch: vi.fn(),
}

const filterDefaults = {
  thingFilterQuery: '',
  thingFilterTypes: [] as string[],
  setThingFilterQuery: vi.fn(),
  toggleThingFilterType: vi.fn(),
  clearThingFilters: vi.fn(),
}

const calendarDefaults = {
  calendarStatus: { configured: false, connected: false },
  calendarEvents: [] as never[],
  fetchCalendarStatus: vi.fn(),
  fetchCalendarEvents: vi.fn(),
  connectCalendar: vi.fn(),
  disconnectCalendar: vi.fn(),
  findings: [],
  dismissFinding: vi.fn(),
  thingTypes: [],
  proactiveSurfaces: [],
  ...searchDefaults,
  ...filterDefaults,
}

beforeEach(() => {
  setDesktopViewport()
})

describe('Sidebar', () => {
  it('shows empty state when no things', () => {
    mockState = { things: [], briefing: [], loading: false, snoozeThing: vi.fn(), ...calendarDefaults }
    render(<Sidebar />)
    expect(screen.getByText('Start by typing in the chat…')).toBeInTheDocument()
  })

  it('renders Things list', () => {
    mockState = {
      things: [makeThing({ title: 'Buy groceries' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    expect(screen.getByText('Buy groceries')).toBeInTheDocument()
  })

  it('shows loading skeleton when loading with no things', () => {
    mockState = { things: [], briefing: [], loading: true, snoozeThing: vi.fn(), ...calendarDefaults }
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
      ...calendarDefaults,
    }
    render(<Sidebar />)
    expect(screen.getByText('Daily Briefing')).toBeInTheDocument()
    expect(screen.getByText('Overdue Task')).toBeInTheDocument()
  })

  it('shows snooze button on ThingCard', () => {
    mockState = {
      things: [makeThing({ title: 'My Thing' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    expect(screen.getByTitle('Snooze')).toBeInTheDocument()
  })

  it('is expanded by default on desktop', () => {
    setDesktopViewport()
    mockState = { things: [], briefing: [], loading: false, snoozeThing: vi.fn(), ...calendarDefaults }
    render(<Sidebar />)
    expect(screen.getByLabelText('Close sidebar')).toBeInTheDocument()
    expect(screen.queryByLabelText('Open sidebar')).not.toBeInTheDocument()
  })

  it('is collapsed by default on mobile', () => {
    setMobileViewport()
    mockState = { things: [], briefing: [], loading: false, snoozeThing: vi.fn(), ...calendarDefaults }
    render(<Sidebar />)
    expect(screen.getByLabelText('Open sidebar')).toBeInTheDocument()
  })

  it('can be toggled open and closed', () => {
    setDesktopViewport()
    mockState = { things: [], briefing: [], loading: false, snoozeThing: vi.fn(), ...calendarDefaults }
    render(<Sidebar />)

    // Initially open on desktop
    expect(screen.getByLabelText('Close sidebar')).toBeInTheDocument()

    // Close it
    fireEvent.click(screen.getByLabelText('Close sidebar'))
    expect(screen.getByLabelText('Open sidebar')).toBeInTheDocument()

    // Open it again
    fireEvent.click(screen.getByLabelText('Open sidebar'))
    expect(screen.getByLabelText('Close sidebar')).toBeInTheDocument()
  })
})
