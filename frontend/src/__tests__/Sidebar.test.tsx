import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { Sidebar } from '../components/Sidebar'

type Thing = {
  id: string
  title: string
  type_hint: string | null
  checkin_date: string | null
  priority: number
  active: boolean
  surface: boolean
  data: Record<string, unknown> | null
  created_at: string
  updated_at: string
  last_referenced: string | null
  open_questions: string[] | null
  children_count: number | null
  completed_count: number | null
  parent_ids: string[] | null
}

let mockState: Record<string, unknown> = {
  things: [] as Thing[],
  briefing: [] as Thing[],
  theOneThing: null,
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
  nudges: [],
  nudgesLoading: false,
  dismissNudge: vi.fn(),
  stopNudgeType: vi.fn(),
  weeklyBriefing: null,
  weeklyBriefingLoading: false,
  fetchWeeklyBriefing: vi.fn(),
  preferenceToasts: [],
  dismissPreferenceToast: vi.fn(),
}

vi.mock('zustand/react/shallow', () => ({
  useShallow: <T,>(fn: (state: unknown) => T) => fn,
}))

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}))

vi.mock('../api', () => ({
  apiFetch: vi.fn().mockResolvedValue({ ok: true }),
}))

const makeThing = (overrides: Partial<Thing> = {}): Thing => ({
  id: 't1',
  title: 'Test Thing',
  type_hint: 'task',
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
  parent_ids: null,
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

const mergeDefaults = {
  mergeSuggestions: [],
  mergeSuggestionsLoading: false,
  mergeInProgress: false,
  executeMerge: vi.fn(),
  dismissMergeSuggestion: vi.fn(),
  fetchMergeSuggestions: vi.fn(),
}

const connectionDefaults = {
  connectionSuggestions: [],
  connectionSuggestionsLoading: false,
  connectionAcceptInProgress: false,
  fetchConnectionSuggestions: vi.fn(),
  acceptConnectionSuggestion: vi.fn(),
  dismissConnectionSuggestion: vi.fn(),
  deferConnectionSuggestion: vi.fn(),
  openThingDetail: vi.fn(),
}

const nudgeDefaults = {
  nudges: [],
  nudgesLoading: false,
  dismissNudge: vi.fn(),
  stopNudgeType: vi.fn(),
  weeklyBriefing: null,
  weeklyBriefingLoading: false,
  fetchWeeklyBriefing: vi.fn(),
  preferenceToasts: [],
  dismissPreferenceToast: vi.fn(),
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
  focusRecommendations: [],
  sidebarOpen: true,
  setSidebarOpen: vi.fn(),
  createThing: vi.fn(),
  ...searchDefaults,
  ...filterDefaults,
  ...mergeDefaults,
  ...connectionDefaults,
  ...nudgeDefaults,
}

beforeEach(() => {
  setDesktopViewport()
})

describe('Sidebar', () => {
  it('shows empty state when no things', () => {
    mockState = { things: [], briefing: [], loading: false, snoozeThing: vi.fn(), ...calendarDefaults }
    render(<Sidebar />)
    expect(screen.getByText('Things you mention in chat appear here')).toBeInTheDocument()
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
    // showBriefing requires 5+ things
    const fiveThings = Array.from({ length: 5 }, (_, i) => makeThing({ id: `t${i}`, title: `Thing ${i}` }))
    mockState = {
      things: fiveThings,
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
    mockState = { things: [], briefing: [], loading: false, snoozeThing: vi.fn(), ...calendarDefaults, sidebarOpen: false }
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

  it('shows Preferences section for preference Things', () => {
    const pref = makeThing({
      id: 'p1',
      title: 'Avoids morning meetings',
      type_hint: 'preference',
      data: { confidence: 0.8, category: 'scheduling', evidence: ['obs1', 'obs2', 'obs3'] },
    })
    mockState = {
      things: [pref],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    expect(screen.getByText('Preferences')).toBeInTheDocument()
    expect(screen.getByText('Avoids morning meetings')).toBeInTheDocument()
    expect(screen.getByText('Strong')).toBeInTheDocument()
    expect(screen.getByText('3 obs.')).toBeInTheDocument()
  })

  it('does not show preference Things in regular type groups', () => {
    const pref = makeThing({ id: 'p1', title: 'My Preference', type_hint: 'preference', data: null })
    const task = makeThing({ id: 't2', title: 'My Task', type_hint: 'task', data: null })
    mockState = {
      things: [pref, task],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    // 'Tasks' group should exist (for the task) but preference should not appear in it
    expect(screen.getByText('Tasks')).toBeInTheDocument()
    expect(screen.getByText('Preferences')).toBeInTheDocument()
    // The preference title appears only once (in Preferences section, not in Tasks)
    expect(screen.getAllByText('My Preference')).toHaveLength(1)
  })

  it('collapses and re-expands a section when its header is clicked', () => {
    mockState = {
      things: [makeThing({ title: 'My Task', type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    expect(screen.getByText('My Task')).toBeInTheDocument()

    const headerButton = screen.getByText('Tasks').closest('button')!
    const section = headerButton.closest('section')!
    const gridWrapper = section.querySelector('.grid')!

    // Initially expanded
    expect(gridWrapper.className).toContain('grid-rows-[1fr]')
    expect(gridWrapper.className).not.toContain('grid-rows-[0fr]')

    // Click to collapse
    fireEvent.click(headerButton)
    expect(gridWrapper.className).toContain('grid-rows-[0fr]')
    expect(gridWrapper.className).not.toContain('grid-rows-[1fr]')

    // Click again to expand
    fireEvent.click(headerButton)
    expect(gridWrapper.className).toContain('grid-rows-[1fr]')
    expect(gridWrapper.className).not.toContain('grid-rows-[0fr]')
  })

  it('shows quick-add input when + button is clicked', () => {
    mockState = {
      things: [makeThing({ title: 'My Task', type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    expect(screen.getByPlaceholderText('Add task…')).toBeInTheDocument()
  })

  it('calls createThing on quick-add submit', async () => {
    const createThing = vi.fn().mockResolvedValue(undefined)
    mockState = {
      things: [makeThing({ title: 'My Task', type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      createThing,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    const input = screen.getByPlaceholderText('Add task…')
    fireEvent.change(input, { target: { value: 'New task title' } })
    fireEvent.submit(input.closest('form')!)
    await waitFor(() => expect(createThing).toHaveBeenCalledWith('New task title', 'task', undefined))
  })

  it('dismisses quick-add input on Escape', () => {
    mockState = {
      things: [makeThing({ title: 'My Task', type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.keyDown(screen.getByPlaceholderText('Add task…'), { key: 'Escape' })
    expect(screen.queryByPlaceholderText('Add task…')).not.toBeInTheDocument()
  })

  it('uses correct singularized placeholder for People section', () => {
    mockState = {
      things: [makeThing({ id: 'p1', title: 'Alice', type_hint: 'person' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add person'))
    expect(screen.getByPlaceholderText('Add person…')).toBeInTheDocument()
  })

  it('calls createThing with checkinDate when date input is filled', async () => {
    const createThing = vi.fn().mockResolvedValue({ id: 'new-1' })
    mockState = {
      things: [makeThing({ type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      createThing,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.change(screen.getByPlaceholderText('Add task…'), { target: { value: 'New task' } })
    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(dateInput, { target: { value: '2026-04-25' } })
    fireEvent.submit(screen.getByPlaceholderText('Add task…').closest('form')!)
    await waitFor(() => expect(createThing).toHaveBeenCalledWith('New task', 'task', '2026-04-25'))
  })

  it('calls createThing without checkinDate when date is empty', async () => {
    const createThing = vi.fn().mockResolvedValue({ id: 'new-2' })
    mockState = {
      things: [makeThing({ type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      createThing,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.change(screen.getByPlaceholderText('Add task…'), { target: { value: 'New task' } })
    fireEvent.submit(screen.getByPlaceholderText('Add task…').closest('form')!)
    await waitFor(() => expect(createThing).toHaveBeenCalledWith('New task', 'task', undefined))
  })

  it('shows parent project selector for task type when projects exist', () => {
    mockState = {
      things: [
        makeThing({ id: 't1', type_hint: 'task' }),
        makeThing({ id: 'p1', title: 'My Project', type_hint: 'project', active: true }),
      ],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    const select = document.querySelector('select') as HTMLSelectElement
    expect(select).toBeInTheDocument()
    const options = Array.from(select.options).map(o => o.textContent)
    expect(options).toContain('No parent project')
    expect(options).toContain('My Project')
  })

  it('calls apiFetch to create relationship when parent is selected', async () => {
    const { apiFetch } = await import('../api')
    const mockedApiFetch = vi.mocked(apiFetch)
    mockedApiFetch.mockResolvedValue({ ok: true } as Response)

    const createThing = vi.fn().mockResolvedValue({ id: 'new-3' })
    mockState = {
      things: [
        makeThing({ id: 't1', type_hint: 'task' }),
        makeThing({ id: 'p1', title: 'My Project', type_hint: 'project', active: true }),
      ],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      createThing,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.change(screen.getByPlaceholderText('Add task…'), { target: { value: 'Child task' } })
    const select = document.querySelector('select') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'p1' } })
    fireEvent.submit(screen.getByPlaceholderText('Add task…').closest('form')!)

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        '/api/things/relationships',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            from_thing_id: 'p1',
            to_thing_id: 'new-3',
            relationship_type: 'parent-of',
          }),
        })
      )
    )
  })

  it('does not call apiFetch for relationships when no parent selected', async () => {
    const { apiFetch } = await import('../api')
    const mockedApiFetch = vi.mocked(apiFetch)
    mockedApiFetch.mockClear()

    const createThing = vi.fn().mockResolvedValue({ id: 'new-4' })
    mockState = {
      things: [makeThing({ type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      createThing,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.change(screen.getByPlaceholderText('Add task…'), { target: { value: 'Solo task' } })
    fireEvent.submit(screen.getByPlaceholderText('Add task…').closest('form')!)

    await waitFor(() => expect(createThing).toHaveBeenCalled())
    expect(mockedApiFetch).not.toHaveBeenCalledWith('/api/things/relationships', expect.anything())
  })

  it('resets checkinDate and parentId on Escape', () => {
    mockState = {
      things: [
        makeThing({ id: 't1', type_hint: 'task' }),
        makeThing({ id: 'p1', title: 'My Project', type_hint: 'project', active: true }),
      ],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    fireEvent.click(screen.getByText('Add task'))
    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(dateInput, { target: { value: '2026-05-01' } })
    const select = document.querySelector('select') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'p1' } })
    fireEvent.keyDown(screen.getByPlaceholderText('Add task…'), { key: 'Escape' })
    // Re-open
    fireEvent.click(screen.getByText('Add task'))
    const dateInputAfter = document.querySelector('input[type="date"]') as HTMLInputElement
    expect(dateInputAfter.value).toBe('')
    const selectAfter = document.querySelector('select') as HTMLSelectElement
    expect(selectAfter.value).toBe('')
  })

  it('renders mobile hero card when theOneThing is set', () => {
    setMobileViewport()
    const oneThing = {
      thing: makeThing({ id: 'ot1', title: 'Finish auth refactor', checkin_date: '2026-04-20' }),
      reasons: ['Overdue by 3 days'],
      importance: 3,
      urgency: 3,
      score: 0.9,
    }
    mockState = {
      things: [makeThing()],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      theOneThing: oneThing,
      ...calendarDefaults,
    }
    render(<Sidebar />)
    expect(screen.getAllByText('Finish auth refactor').length).toBeGreaterThan(0)
    expect(screen.getAllByText('The One Thing').length).toBeGreaterThan(0)
  })

  it('renders user avatar on mobile when currentUser has picture', () => {
    setMobileViewport()
    mockState = {
      things: [],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      currentUser: { id: 'u1', name: 'Alex', email: 'alex@example.com', picture: 'https://example.com/avatar.jpg' },
      ...calendarDefaults,
    }
    render(<Sidebar />)
    const avatars = screen.getAllByAltText('Alex')
    expect(avatars.length).toBeGreaterThan(0)
    expect(avatars[0]).toHaveAttribute('src', 'https://example.com/avatar.jpg')
  })
})

describe('Sidebar: progressive disclosure thresholds', () => {
  const weeklyBriefingMock = {
    id: 'wb1',
    week_start: '2026-04-14',
    generated_at: '2026-04-18T08:00:00Z',
    content: {
      summary: 'A great week',
      week_start: '2026-04-14',
      week_end: '2026-04-18',
      completed: [],
      upcoming: [],
      new_connections: [],
      preferences_learned: [],
      open_questions: [],
      stats: {},
    },
  }

  it('does not show Weekly Digest with 99 things', () => {
    const things = Array.from({ length: 99 }, (_, i) => makeThing({ id: `t${i}`, title: `Thing ${i}` }))
    mockState = {
      things,
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      weeklyBriefing: weeklyBriefingMock,
    }
    render(<Sidebar />)
    expect(screen.queryByText('Weekly Digest')).not.toBeInTheDocument()
  })

  it('shows Weekly Digest with 100+ things', () => {
    const things = Array.from({ length: 100 }, (_, i) => makeThing({ id: `t${i}`, title: `Thing ${i}` }))
    mockState = {
      things,
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      weeklyBriefing: weeklyBriefingMock,
    }
    render(<Sidebar />)
    expect(screen.getByText('Weekly Digest')).toBeInTheDocument()
  })

  it('does not show Morning Briefing with fewer than 5 things', () => {
    const overdueDate = '2026-01-01T00:00:00Z'
    mockState = {
      things: [makeThing({ id: 't0', title: 'Thing 0' })],
      briefing: [makeThing({ id: 'b1', title: 'Overdue Task', checkin_date: overdueDate })],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    expect(screen.queryByText('Morning Briefing')).not.toBeInTheDocument()
  })

  it('shows Focus section with 20+ things when recommendations exist', () => {
    const things = Array.from({ length: 20 }, (_, i) => makeThing({ id: `t${i}`, title: `Thing ${i}` }))
    mockState = {
      things,
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      focusRecommendations: [{ thing: makeThing({ id: 'fr1', title: 'Focus Me' }), reasons: ['High priority'], score: 0.9 }],
    }
    render(<Sidebar />)
    expect(screen.getByText('Focus')).toBeInTheDocument()
  })

  it('does not show Focus section with 19 things', () => {
    const things = Array.from({ length: 19 }, (_, i) => makeThing({ id: `t${i}`, title: `Thing ${i}` }))
    mockState = {
      things,
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
      focusRecommendations: [{ thing: makeThing({ id: 'fr1', title: 'Focus Me' }), reasons: ['High priority'], score: 0.9 }],
    }
    render(<Sidebar />)
    expect(screen.queryByText('Focus')).not.toBeInTheDocument()
  })
})

describe('Sidebar: completed tasks display', () => {
  it('shows completed task at bottom of Tasks section after checkbox click', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const updateThing = vi.fn().mockResolvedValue(undefined)
    mockState = {
      things: [makeThing({ title: 'Finish report', type_hint: 'task' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      updateThing,
      ...calendarDefaults,
    }

    render(<Sidebar />)

    // Initially no completed section
    expect(screen.getByText('Finish report')).toBeInTheDocument()
    const checkbox = screen.getByLabelText('Mark task done')

    fireEvent.click(checkbox)

    // Advance past the 600ms animation delay
    await vi.advanceTimersByTimeAsync(700)

    expect(updateThing).toHaveBeenCalledWith(expect.any(String), { active: false })

    // Completed item appears with strikethrough class
    const completedItems = document.querySelectorAll('.line-through')
    expect(completedItems.length).toBeGreaterThan(0)
    expect(completedItems[0]!.textContent).toBe('Finish report')

    vi.useRealTimers()
  })

  it('does not show completed section for non-task groups', () => {
    mockState = {
      things: [makeThing({ id: 'p1', title: 'Alice', type_hint: 'person' })],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      ...calendarDefaults,
    }
    render(<Sidebar />)
    // No completed section since no tasks were completed
    expect(document.querySelector('.line-through')).not.toBeInTheDocument()
  })

  it('deduplicates completed tasks when same task is completed twice', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const updateThing = vi.fn().mockResolvedValue(undefined)
    const thing = makeThing({ title: 'Dedupe task', type_hint: 'task' })
    mockState = {
      things: [thing],
      briefing: [],
      loading: false,
      snoozeThing: vi.fn(),
      updateThing,
      ...calendarDefaults,
    }

    render(<Sidebar />)
    const checkbox = screen.getByLabelText('Mark task done')

    // Complete the task once
    fireEvent.click(checkbox)
    await vi.advanceTimersByTimeAsync(700)

    // Verify exactly one completed entry (not duplicated)
    expect(document.querySelectorAll('.line-through').length).toBe(1)

    vi.useRealTimers()
  })
})
