import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CommandPalette } from '../components/CommandPalette'

const closeCommandPalette = vi.fn()
const openQuickAdd = vi.fn()
const searchThings = vi.fn()
const clearSearch = vi.fn()
const openThingDetail = vi.fn()
const setMainView = vi.fn()

let mockMainView = 'list'

const mockThings = [
  {
    id: 't1',
    title: 'Send proposal draft',
    type_hint: 'task' as const,
    active: true,
    updated_at: '2026-04-18T10:00:00Z',
    checkin_date: null,
    priority: 1,
    importance: 2,
    surface: true,
    data: null,
    created_at: '2026-04-18T00:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: null,
    completed_count: null,
    parent_ids: null,
  },
  {
    id: 't2',
    title: 'Website redesign',
    type_hint: 'project' as const,
    active: true,
    updated_at: '2026-04-17T10:00:00Z',
    checkin_date: null,
    priority: 1,
    importance: 2,
    surface: true,
    data: null,
    created_at: '2026-04-17T00:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: null,
    completed_count: null,
    parent_ids: null,
  },
]

vi.mock('../store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      closeCommandPalette,
      openQuickAdd,
      setSidebarOpen: vi.fn(),
      sidebarOpen: false,
      setChatMode: vi.fn(),
      chatMode: 'normal',
      focusChatInput: vi.fn(),
      openSettings: vi.fn(),
      searchThings,
      clearSearch,
      searchResults: mockThings,
      searchLoading: false,
      things: mockThings,
      thingTypes: [],
      openThingDetail,
      mainView: mockMainView,
      setMainView,
    }),
}))

beforeEach(() => {
  closeCommandPalette.mockReset()
  searchThings.mockReset()
  clearSearch.mockReset()
  openThingDetail.mockReset()
  setMainView.mockReset()
  mockMainView = 'list'
})

describe('CommandPalette', () => {
  it('renders search input', () => {
    render(<CommandPalette />)
    expect(screen.getByPlaceholderText('Search everything…')).toBeInTheDocument()
  })

  it('shows recent Things in empty state', () => {
    render(<CommandPalette />)
    expect(screen.getByText('Send proposal draft')).toBeInTheDocument()
    expect(screen.getByText('Website redesign')).toBeInTheDocument()
  })

  it('calls searchThings after typing', async () => {
    render(<CommandPalette />)
    fireEvent.change(screen.getByPlaceholderText('Search everything…'), { target: { value: 'proposal' } })
    await vi.waitFor(() => expect(searchThings).toHaveBeenCalledWith('proposal'), { timeout: 400 })
  })

  it('opens Thing detail on Enter', () => {
    render(<CommandPalette />)
    fireEvent.keyDown(screen.getByPlaceholderText('Search everything…'), { key: 'Enter' })
    expect(openThingDetail).toHaveBeenCalledWith('t1')
    expect(closeCommandPalette).toHaveBeenCalled()
  })

  it('closes on Escape', () => {
    render(<CommandPalette />)
    fireEvent.keyDown(screen.getByPlaceholderText('Search everything…'), { key: 'Escape' })
    expect(closeCommandPalette).toHaveBeenCalled()
  })

  it('hides Things group with > prefix', () => {
    render(<CommandPalette />)
    fireEvent.change(screen.getByPlaceholderText('Search everything…'), { target: { value: '> new' } })
    expect(screen.queryByText('Send proposal draft')).not.toBeInTheDocument()
  })

  it('filters Things by type with # prefix and hides Quick Actions group', () => {
    render(<CommandPalette />)
    fireEvent.change(screen.getByPlaceholderText('Search everything…'), { target: { value: '#task' } })
    // Only the task-type Thing should appear (t1), not the project-type (t2)
    expect(screen.getByText('Send proposal draft')).toBeInTheDocument()
    expect(screen.queryByText('Website redesign')).not.toBeInTheDocument()
    // Actions group should be suppressed when typeFilter is active
    expect(screen.queryByText(/Quick Actions/i)).not.toBeInTheDocument()
  })

  it('calls searchThings with text portion when # prefix has trailing query', async () => {
    render(<CommandPalette />)
    fireEvent.change(screen.getByPlaceholderText('Search everything…'), { target: { value: '#task proposal' } })
    await vi.waitFor(() => expect(searchThings).toHaveBeenCalledWith('proposal'), { timeout: 400 })
  })

  it('navigates to second item with ArrowDown then opens it on Enter', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search everything…')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(openThingDetail).toHaveBeenCalledWith('t2')
    expect(closeCommandPalette).toHaveBeenCalled()
  })

  it('opens Thing detail on click', () => {
    render(<CommandPalette />)
    fireEvent.mouseDown(screen.getByText('Send proposal draft'))
    expect(openThingDetail).toHaveBeenCalledWith('t1')
    expect(closeCommandPalette).toHaveBeenCalled()
  })

  it('clears search results on unmount', () => {
    const { unmount } = render(<CommandPalette />)
    unmount()
    expect(clearSearch).toHaveBeenCalled()
  })

  it('shows "Switch to Calendar View" when in list view', () => {
    mockMainView = 'list'
    render(<CommandPalette />)
    expect(screen.getByText('Switch to Calendar View')).toBeInTheDocument()
  })

  it('shows "Switch to List View" when in calendar view', () => {
    mockMainView = 'calendar'
    render(<CommandPalette />)
    expect(screen.getByText('Switch to List View')).toBeInTheDocument()
  })

  it('calls setMainView("calendar") when calendar command executed from list view', () => {
    mockMainView = 'list'
    render(<CommandPalette />)
    fireEvent.mouseDown(screen.getByText('Switch to Calendar View'))
    expect(setMainView).toHaveBeenCalledWith('calendar')
    expect(closeCommandPalette).toHaveBeenCalled()
  })
})
