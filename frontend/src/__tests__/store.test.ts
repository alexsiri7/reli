import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useStore } from '../store'

const mockThing = {
  id: 't1',
  title: 'Test Thing',
  type_hint: 'task' as const,
  parent_id: null,
  checkin_date: null,
  priority: 2,
  active: true,
  surface: true,
  data: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  last_referenced: null,
  children_count: null,
  completed_count: null,
}

beforeEach(() => {
  useStore.setState({
    things: [],
    briefing: [],
    messages: [],
    loading: false,
    chatLoading: false,
    error: null,
  })
  vi.restoreAllMocks()
})

describe('store: fetchThings', () => {
  it('sets things on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [mockThing],
    }))

    await useStore.getState().fetchThings()

    expect(useStore.getState().things).toEqual([mockThing])
    expect(useStore.getState().loading).toBe(false)
    expect(useStore.getState().error).toBeNull()
  })

  it('sets error on HTTP failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => [],
    }))

    await useStore.getState().fetchThings()

    expect(useStore.getState().error).toMatch(/500/)
    expect(useStore.getState().things).toEqual([])
  })
})

describe('store: snoozeThing', () => {
  it('updates thing checkin_date on success', async () => {
    const updated = { ...mockThing, checkin_date: '2026-01-08T00:00:00.000Z' }
    useStore.setState({ things: [mockThing] })

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => updated,
    }))

    await useStore.getState().snoozeThing('t1', '2026-01-08T00:00:00.000Z')

    expect(useStore.getState().things[0].checkin_date).toBe('2026-01-08T00:00:00.000Z')
  })

  it('sets error when PATCH fails', async () => {
    useStore.setState({ things: [mockThing] })

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))

    await useStore.getState().snoozeThing('t1', '2026-01-08T00:00:00.000Z')

    expect(useStore.getState().error).toMatch(/404/)
  })
})

describe('store: sendMessage', () => {
  it('adds user and assistant messages', async () => {
    const savedMsg = {
      id: 'saved-1',
      session_id: 'test',
      role: 'assistant' as const,
      content: 'Got it!',
      applied_changes: null,
      timestamp: '2026-01-01T00:00:00Z',
    }

    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) })  // persist user
      .mockResolvedValueOnce({ ok: true, json: async () => savedMsg }) // persist assistant
      .mockResolvedValue({ ok: true, json: async () => [] }), // fetchThings + fetchBriefing
    )

    await useStore.getState().sendMessage('hello')

    const messages = useStore.getState().messages
    expect(messages.some(m => m.role === 'user' && m.content === 'hello')).toBe(true)
    expect(messages.some(m => m.role === 'assistant')).toBe(true)
    expect(useStore.getState().chatLoading).toBe(false)
  })
})

describe('store: clearError', () => {
  it('clears error state', () => {
    useStore.setState({ error: 'some error' })
    useStore.getState().clearError()
    expect(useStore.getState().error).toBeNull()
  })
})
