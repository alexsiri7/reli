import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CommandPalette } from '../components/CommandPalette'
import type { Thing } from '../store'

const closeCommandPalette = vi.fn()
const openThingDetail = vi.fn()
const openSettings = vi.fn()
const toggleSidebar = vi.fn()
const setMainView = vi.fn()
const setMobileView = vi.fn()
const openFeedback = vi.fn()

let storeState: Record<string, unknown> = {}

vi.mock('../store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) => selector(storeState),
}))

vi.mock('zustand/react/shallow', () => ({
  useShallow: (fn: unknown) => fn,
}))

const makeThing = (overrides: Partial<Thing> = {}): Thing => ({
  id: 't1',
  title: 'My Thing',
  type_hint: 'task',
  parent_id: null,
  checkin_date: null,
  priority: 3,
  active: true,
  surface: false,
  data: null,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  last_referenced: null,
  open_questions: null,
  children_count: null,
  completed_count: null,
  ...overrides,
})

beforeEach(() => {
  closeCommandPalette.mockReset()
  openThingDetail.mockReset()
  openSettings.mockReset()
  toggleSidebar.mockReset()
  setMainView.mockReset()
  setMobileView.mockReset()
  openFeedback.mockReset()

  storeState = {
    commandPaletteOpen: true,
    closeCommandPalette,
    things: [] as Thing[],
    openThingDetail,
    openSettings,
    toggleSidebar,
    setMainView,
    setMobileView,
    openFeedback,
  }
})

describe('CommandPalette', () => {
  it('renders nothing when commandPaletteOpen is false', () => {
    storeState.commandPaletteOpen = false
    const { container } = render(<CommandPalette />)
    expect(container.innerHTML).toBe('')
  })

  it('renders the search input when open', () => {
    render(<CommandPalette />)
    expect(screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')).toBeInTheDocument()
  })

  it('shows recent Things when query is empty', () => {
    storeState.things = [
      makeThing({ id: 't1', title: 'Alpha Task', type_hint: 'task' }),
      makeThing({ id: 't2', title: 'Beta Project', type_hint: 'project' }),
    ]
    render(<CommandPalette />)
    expect(screen.getByText('Recent Things')).toBeInTheDocument()
    expect(screen.getByText('Alpha Task')).toBeInTheDocument()
    expect(screen.getByText('Beta Project')).toBeInTheDocument()
  })

  it('shows actions in > mode', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '>' } })
    expect(screen.getByText('Actions')).toBeInTheDocument()
    expect(screen.getByText('New Thing')).toBeInTheDocument()
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('filters commands by label in > mode with text', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '> settings' } })
    expect(screen.getByText('Settings')).toBeInTheDocument()
    expect(screen.queryByText('New Thing')).not.toBeInTheDocument()
    expect(screen.queryByText('Toggle Sidebar')).not.toBeInTheDocument()
  })

  it('filters Things by type with #type prefix', () => {
    storeState.things = [
      makeThing({ id: 't1', title: 'Alpha Task', type_hint: 'task' }),
      makeThing({ id: 't2', title: 'Beta Project', type_hint: 'project' }),
    ]
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '#task' } })
    expect(screen.getByText('Alpha Task')).toBeInTheDocument()
    expect(screen.queryByText('Beta Project')).not.toBeInTheDocument()
  })

  it('filters Things by type AND text with #type query combination', () => {
    storeState.things = [
      makeThing({ id: 't1', title: 'Roadmap Project', type_hint: 'project' }),
      makeThing({ id: 't2', title: 'Roadmap Task', type_hint: 'task' }),
    ]
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '#project roadmap' } })
    expect(screen.getByText('Roadmap Project')).toBeInTheDocument()
    expect(screen.queryByText('Roadmap Task')).not.toBeInTheDocument()
  })

  it('opens thing detail on Enter when a Thing is selected', () => {
    storeState.things = [
      makeThing({ id: 'thing1', title: 'My Task', type_hint: 'task' }),
    ]
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(openThingDetail).toHaveBeenCalledWith('thing1')
  })

  it('runs command on Enter when a command is selected', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '>' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(setMobileView).toHaveBeenCalledWith('chat')
  })

  it('ArrowDown navigates to next item and ArrowUp goes back', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '>' } })
    // idx 0 = New Thing, idx 1 = Toggle Sidebar
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(toggleSidebar).toHaveBeenCalled()
  })

  it('ArrowUp clamps at index 0 and does not go negative', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '>' } })
    // Press ArrowUp at idx 0 — should stay at 0 (New Thing)
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(setMobileView).toHaveBeenCalledWith('chat')
  })

  it('ArrowDown then ArrowUp navigates forward and back', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: '>' } })
    // Down twice to idx 2 (Switch to Graph View), Up once to idx 1 (Toggle Sidebar), Enter
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(toggleSidebar).toHaveBeenCalled()
  })

  it('closes on Escape', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(closeCommandPalette).toHaveBeenCalled()
  })

  it('shows "No results" when no things or actions match', () => {
    render(<CommandPalette />)
    const input = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
    fireEvent.change(input, { target: { value: 'zzzznotfound12345' } })
    expect(screen.getByText('No results')).toBeInTheDocument()
  })

  it('opens thing via click', () => {
    storeState.things = [
      makeThing({ id: 'thing1', title: 'Click Me', type_hint: 'task' }),
    ]
    render(<CommandPalette />)
    fireEvent.click(screen.getByText('Click Me'))
    expect(openThingDetail).toHaveBeenCalledWith('thing1')
  })

  it('closes on backdrop click', () => {
    render(<CommandPalette />)
    // The outermost div is the backdrop
    const backdrop = screen.getByPlaceholderText('Search things or type > for actions, #type to filter…')
      .closest('.fixed')!
    fireEvent.click(backdrop)
    expect(closeCommandPalette).toHaveBeenCalled()
  })
})
