import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CommandPalette } from '../components/CommandPalette'

const closeCommandPalette = vi.fn()
const openQuickAdd = vi.fn()
const searchThings = vi.fn()
const clearSearch = vi.fn()
const openThingDetail = vi.fn()

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
    }),
}))

beforeEach(() => {
  closeCommandPalette.mockReset()
  searchThings.mockReset()
  clearSearch.mockReset()
  openThingDetail.mockReset()
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
})
