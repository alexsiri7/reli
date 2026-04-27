import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BriefingPanel, DueTodayRow, TodayEventRow } from '../components/BriefingPanel'
import type { BriefingItem, CalendarEvent } from '../store'

const makeOneThing = (): BriefingItem => ({
  thing: { id: 'hero-1', title: 'Ship the auth refactor', active: true, checkin_date: '2026-04-28' } as BriefingItem['thing'],
  importance: 3, urgency: 0.9, score: 2.7,
  reasons: ['Overdue'],
})

let mockBriefingState = {
  theOneThing: null as BriefingItem | null,
  secondaryItems: [] as BriefingItem[],
  briefingStats: null,
  findings: [] as unknown[],
  learnedPreferences: [] as unknown[],
  nudges: [] as unknown[],
  morningBriefing: null,
  calendarEvents: [] as CalendarEvent[],
  error: null,
  currentUser: null,
  setRightView: vi.fn(),
  dismissFinding: vi.fn(),
  snoozeFinding: vi.fn(),
  actOnFinding: vi.fn(),
  submitPreferenceFeedback: vi.fn(),
  updateThing: vi.fn(),
  snoozeThing: vi.fn(),
  openChatWithContext: vi.fn(),
  continueInChat: vi.fn(),
}

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockBriefingState) => unknown) => selector(mockBriefingState),
  serialiseMorningBriefing: vi.fn(),
}))

vi.mock('zustand/react/shallow', () => ({
  useShallow: <T,>(fn: (state: unknown) => T) => fn,
}))

vi.mock('../components/NudgeBanner', () => ({
  NudgeBanner: () => null,
}))

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

describe('BriefingPanel hero card', () => {
  beforeEach(() => {
    mockBriefingState = {
      theOneThing: null,
      secondaryItems: [],
      briefingStats: null,
      findings: [],
      learnedPreferences: [],
      nudges: [],
      morningBriefing: null,
      calendarEvents: [],
      error: null,
      currentUser: null,
      setRightView: vi.fn(),
      dismissFinding: vi.fn(),
      snoozeFinding: vi.fn(),
      actOnFinding: vi.fn(),
      submitPreferenceFeedback: vi.fn(),
      updateThing: vi.fn(),
      snoozeThing: vi.fn(),
      openChatWithContext: vi.fn(),
      continueInChat: vi.fn(),
    }
  })

  it('does not render hero card when theOneThing is null', () => {
    render(<BriefingPanel />)
    expect(screen.queryByText('Most Important')).not.toBeInTheDocument()
  })

  it('renders hero card with title when theOneThing is set', () => {
    mockBriefingState = { ...mockBriefingState, theOneThing: makeOneThing() }
    render(<BriefingPanel />)
    expect(screen.getByText('Ship the auth refactor')).toBeInTheDocument()
    expect(screen.getByText('Most Important')).toBeInTheDocument()
  })

  it('calls updateThing with active:false when Done clicked', () => {
    const updateThing = vi.fn()
    mockBriefingState = { ...mockBriefingState, theOneThing: makeOneThing(), updateThing }
    render(<BriefingPanel />)
    fireEvent.click(screen.getByText('Done'))
    expect(updateThing).toHaveBeenCalledWith('hero-1', { active: false })
  })

  it('calls openChatWithContext with id and title when Chat clicked', () => {
    const openChatWithContext = vi.fn()
    mockBriefingState = { ...mockBriefingState, theOneThing: makeOneThing(), openChatWithContext }
    render(<BriefingPanel />)
    // The header also has a "Chat" button — pick the last one (hero card)
    const chatButtons = screen.getAllByText('Chat')
    fireEvent.click(chatButtons.at(-1)!)
    expect(openChatWithContext).toHaveBeenCalledWith('hero-1', 'Ship the auth refactor')
  })

  it('shows hero card (not empty state) when only theOneThing is set', () => {
    mockBriefingState = {
      ...mockBriefingState,
      theOneThing: makeOneThing(),
      secondaryItems: [],
      findings: [],
      learnedPreferences: [],
      calendarEvents: [],
    }
    render(<BriefingPanel />)
    expect(screen.getByText('Most Important')).toBeInTheDocument()
    expect(screen.queryByText(/nothing due/i)).not.toBeInTheDocument()
  })

  it('does not render theOneThing in Due Today section', () => {
    const secondary: BriefingItem = {
      thing: { id: 'sec-1', title: 'Secondary task', active: true } as BriefingItem['thing'],
      importance: 1, urgency: 0.5, score: 0.5, reasons: ['Check in'],
    }
    mockBriefingState = {
      ...mockBriefingState,
      theOneThing: makeOneThing(),
      secondaryItems: [secondary],
    }
    render(<BriefingPanel />)
    expect(screen.getByText('Ship the auth refactor')).toBeInTheDocument()
    expect(screen.getByText('Secondary task')).toBeInTheDocument()
    expect(screen.getAllByText('Ship the auth refactor')).toHaveLength(1)
  })
})
