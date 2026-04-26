import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useStore } from '../store'

const mockThing = {
  id: 't1',
  title: 'Test Thing',
  type_hint: 'task' as const,
  checkin_date: null,
  priority: 2,
  importance: 2,
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
}

beforeEach(() => {
  useStore.setState({
    things: [],
    briefing: [],
    findings: [],
    messages: [],
    loading: false,
    chatLoading: false,
    error: null,
    chatSessions: [],
    chatSessionsLoading: false,
    sessionId: '',
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

    expect(useStore.getState().things[0]!.checkin_date).toBe('2026-01-08T00:00:00.000Z')
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

describe('store: sendMessage — 429 handling', () => {
  it('replaces streaming placeholder with rate-limit message using retry_after from response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 429,
      ok: false,
      json: async () => ({ retry_after: 30 }),
    }))

    await useStore.getState().sendMessage('hello')

    const messages = useStore.getState().messages
    const assistantMsg = messages.find(m => m.role === 'assistant')
    expect(assistantMsg?.content).toBe(
      'Too many requests — please wait 30 seconds before sending another message.'
    )
    expect(assistantMsg?.streaming).toBe(false)
    expect(assistantMsg?.streamingStage).toBeNull()
    expect(useStore.getState().chatLoading).toBe(false)
  })

  it('defaults to 60 seconds when response body is not valid JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 429,
      ok: false,
      json: async () => { throw new SyntaxError('bad json') },
    }))

    await useStore.getState().sendMessage('hello')

    const assistantMsg = useStore.getState().messages.find(m => m.role === 'assistant')
    expect(assistantMsg?.content).toBe(
      'Too many requests — please wait 60 seconds before sending another message.'
    )
    expect(assistantMsg?.streaming).toBe(false)
    expect(useStore.getState().chatLoading).toBe(false)
  })

  it('uses singular "second" when retry_after is 1', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 429,
      ok: false,
      json: async () => ({ retry_after: 1 }),
    }))

    await useStore.getState().sendMessage('hello')

    const assistantMsg = useStore.getState().messages.find(m => m.role === 'assistant')
    expect(assistantMsg?.content).toBe(
      'Too many requests — please wait 1 second before sending another message.'
    )
    expect(assistantMsg?.streaming).toBe(false)
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

describe('store: openChatWithContext', () => {
  it('sets chatPrefill, rightView, mobileView', () => {
    useStore.getState().openChatWithContext('thing-1', 'Write proposal')
    const state = useStore.getState()
    expect(state.chatPrefill).toBe('Let\'s talk about "Write proposal"')
    expect(state.rightView).toBe('chat')
    expect(state.mobileView).toBe('chat')
  })
})

describe('store: clearChatPrefill', () => {
  it('nulls chatPrefill', () => {
    useStore.setState({ chatPrefill: 'something' })
    useStore.getState().clearChatPrefill()
    expect(useStore.getState().chatPrefill).toBeNull()
  })
})

describe('store: stopNudgeType', () => {
  const mockNudge = {
    id: 'proactive_abc123_birthday',
    nudge_type: 'approaching_date',
    message: 'birthday reminder',
    thing_id: 'abc123',
    thing_title: 'Birthday',
    thing_type_hint: null,
    days_away: 3,
    primary_action_label: null,
  }

  beforeEach(() => {
    useStore.setState({
      nudges: [mockNudge],
      preferenceToasts: [],
    })
  })

  it('adds a preferenceToast when backend returns preference', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          suppressed_type: 'approaching_date',
          preference: {
            id: 'pref-abc12345',
            title: 'Prefers fewer date-based reminders',
            confidence_label: 'moderate',
            action: 'created',
          },
        }),
      })
      .mockResolvedValue({ ok: true, json: async () => [] }) // fetchBriefing
    )

    await useStore.getState().stopNudgeType('proactive_abc123_birthday')

    const toasts = useStore.getState().preferenceToasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0]!.title).toBe('Prefers fewer date-based reminders')
    expect(toasts[0]!.confidenceLabel).toBe('moderate')
    expect(toasts[0]!.action).toBe('created')
  })

  it('does not add a toast when backend returns no preference (unknown nudge type)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, suppressed_type: 'future' }),
    }))

    await useStore.getState().stopNudgeType('future_xyz_birthday')

    expect(useStore.getState().preferenceToasts).toHaveLength(0)
  })

  it('removes the nudge optimistically', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, suppressed_type: 'approaching_date' }),
    }))

    await useStore.getState().stopNudgeType('proactive_abc123_birthday')

    expect(useStore.getState().nudges.find(n => n.id === 'proactive_abc123_birthday')).toBeUndefined()
  })
})

const mockSession = (id: string, title = 'Test'): import('../store').ChatSession => ({
  id,
  title,
  created_at: '2026-01-01T00:00:00Z',
  last_active_at: '2026-01-01T00:00:00Z',
  message_count: 0,
})

describe('store: fetchChatSessions', () => {
  it('populates chatSessions on success', async () => {
    const sessions = [mockSession('s1', 'First')]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => sessions }))

    await useStore.getState().fetchChatSessions()

    expect(useStore.getState().chatSessions).toEqual(sessions)
    expect(useStore.getState().chatSessionsLoading).toBe(false)
  })

  it('leaves chatSessions unchanged on HTTP error', async () => {
    useStore.setState({ chatSessions: [mockSession('existing')] })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))

    await useStore.getState().fetchChatSessions()

    expect(useStore.getState().chatSessions).toHaveLength(1)
    expect(useStore.getState().chatSessionsLoading).toBe(false)
  })
})

describe('store: createChatSession', () => {
  it('sets sessionId, clears messages, writes localStorage on success', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => mockSession('new-id') })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
    )
    const setItem = vi.spyOn(Storage.prototype, 'setItem')

    const sessionId = await useStore.getState().createChatSession()

    expect(sessionId).toBeTruthy()
    expect(useStore.getState().sessionId).toBe(sessionId)
    expect(useStore.getState().messages).toEqual([])
    expect(setItem).toHaveBeenCalledWith('reli-active-session', sessionId)
  })

  it('returns null and sets error on API failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, text: async () => 'Server error' }))

    const sessionId = await useStore.getState().createChatSession()

    expect(sessionId).toBeNull()
    expect(useStore.getState().error).toContain('Could not create session')
  })
})

describe('store: renameChatSession', () => {
  it('updates title in chatSessions on success', async () => {
    useStore.setState({ chatSessions: [mockSession('s1', 'Old Name')] })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))

    await useStore.getState().renameChatSession('s1', 'New Name')

    expect(useStore.getState().chatSessions[0]?.title).toBe('New Name')
    expect(useStore.getState().error).toBeNull()
  })

  it('sets error and re-syncs sessions on failure', async () => {
    useStore.setState({ chatSessions: [mockSession('s1', 'Old Name')] })
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: true, json: async () => [mockSession('s1', 'Old Name')] })
    )

    await useStore.getState().renameChatSession('s1', 'New Name')

    expect(useStore.getState().error).toContain('Could not rename session')
  })
})

describe('store: deleteChatSession', () => {
  it('switches to first remaining session when active session is deleted', async () => {
    const sessions = [mockSession('active', 'Active'), mockSession('other', 'Other')]
    useStore.setState({ sessionId: 'active', chatSessions: sessions })
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
    )

    await useStore.getState().deleteChatSession('active')

    expect(useStore.getState().sessionId).toBe('other')
  })

  it('creates a new session when last session is deleted', async () => {
    useStore.setState({ sessionId: 'only', chatSessions: [mockSession('only', 'Only')] })
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValue({ ok: true, json: async () => [] })
    )

    await useStore.getState().deleteChatSession('only')

    expect(useStore.getState().sessionId).not.toBe('only')
  })

  it('sets error on delete failure', async () => {
    useStore.setState({ chatSessions: [mockSession('s1')] })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))

    await useStore.getState().deleteChatSession('s1')

    expect(useStore.getState().error).toContain('Could not delete session')
  })
})
