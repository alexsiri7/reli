import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useStore, serialiseMorningBriefing, serialiseWeeklyBriefing } from '../store'

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

describe('store: continueInChat', () => {
  beforeEach(() => {
    useStore.setState({ sessions: [], error: null, rightView: 'briefing', mobileView: 'briefing' })
  })

  it('sets rightView and mobileView to chat on success', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'new-sess-1', title: 'Morning briefing', origin: 'morning_briefing', created_at: '', last_active_at: '' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => [] }),
    )

    await useStore.getState().continueInChat('briefing text', 'Morning briefing', 'morning_briefing', 'What do you want to focus on?')

    const state = useStore.getState()
    expect(state.rightView).toBe('chat')
    expect(state.mobileView).toBe('chat')
    expect(state.error).toBeNull()
  })

  it('sets error when session creation fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: false, status: 500 }))

    await useStore.getState().continueInChat('text', 'title', 'morning_briefing', 'opening')

    expect(useStore.getState().error).toMatch(/Failed to create session/)
  })

  it('sets error when system message seed fails', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'sess-1', title: 't', origin: null, created_at: '', last_active_at: '' }) })
      .mockResolvedValueOnce({ ok: false, status: 413 }),
    )

    await useStore.getState().continueInChat('text', 'title', 'morning_briefing', 'opening')

    expect(useStore.getState().error).toMatch(/Failed to seed system message/)
  })
})

describe('serialiseMorningBriefing', () => {
  it('includes date and summary', () => {
    const result = serialiseMorningBriefing({
      briefing_date: '2026-04-26',
      content: {
        summary: 'Busy day ahead',
        priorities: [],
        overdue: [],
        blockers: [],
        findings: [],
      },
    } as never)
    expect(result).toContain('2026-04-26')
    expect(result).toContain('Busy day ahead')
  })

  it('includes first reason for priority items', () => {
    const result = serialiseMorningBriefing({
      briefing_date: '2026-04-26',
      content: {
        summary: '',
        priorities: [{ title: 'Write proposal', reasons: ['High priority', 'Due today'] }],
        overdue: [],
        blockers: [],
        findings: [],
      },
    } as never)
    expect(result).toContain('Write proposal')
    expect(result).toContain('High priority')
    expect(result).not.toContain('Due today')
  })

  it('handles empty priorities gracefully', () => {
    const result = serialiseMorningBriefing({
      briefing_date: '2026-04-26',
      content: { summary: '', priorities: [], overdue: [], blockers: [], findings: [] },
    } as never)
    expect(result).not.toContain('Priorities:')
  })
})

describe('serialiseWeeklyBriefing', () => {
  it('includes week_start and summary', () => {
    const result = serialiseWeeklyBriefing({
      week_start: '2026-04-21',
      content: {
        summary: 'Good progress',
        completed: [],
        upcoming: [],
        open_questions: [],
      },
    } as never)
    expect(result).toContain('2026-04-21')
    expect(result).toContain('Good progress')
  })

  it('handles empty sections gracefully', () => {
    const result = serialiseWeeklyBriefing({
      week_start: '2026-04-21',
      content: { summary: '', completed: [], upcoming: [], open_questions: [] },
    } as never)
    expect(result).not.toContain('Completed this week:')
    expect(result).not.toContain('Upcoming:')
  })
})
