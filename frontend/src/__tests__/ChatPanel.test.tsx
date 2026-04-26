import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { Nudge } from '../generated/api-types'

type Msg = {
  id: string | number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  applied_changes: null
  questions_for_user: string[]
  timestamp: string
  streaming?: boolean
  prompt_tokens?: number
  completion_tokens?: number
  cost_usd?: number
  model?: string | null
}

const mockClearChatPrefill = vi.fn()

const mockStore = {
  messages: [] as Msg[],
  things: [] as unknown[],
  chatLoading: false,
  historyLoading: false,
  hasMoreHistory: false,
  sendMessage: vi.fn(),
  fetchOlderMessages: vi.fn(),
  sessionStats: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, api_calls: 0, cost_usd: 0, per_model: [] },
  registerChatInputFocus: vi.fn(),
  seedFromGoogle: vi.fn().mockResolvedValue({ count: 0 }),
  googleSeedLoading: false,
  calendarStatus: { configured: false, connected: false },
  nudges: [] as Nudge[],
  chatPrefill: null as string | null,
  clearChatPrefill: mockClearChatPrefill,
  sessions: [] as unknown[],
  sessionId: '' as string,
}

const mockDismissNudge = vi.fn()
const mockStopNudgeType = vi.fn()
const mockOpenThingDetail = vi.fn()

vi.mock('../store', () => ({
  useStore: Object.assign(
    (selector: (s: typeof mockStore) => unknown) => selector(mockStore),
    {
      getState: () => ({
        dismissNudge: mockDismissNudge,
        stopNudgeType: mockStopNudgeType,
        openThingDetail: mockOpenThingDetail,
      }),
    }
  ),
}))

vi.mock('../hooks/useVoiceInput', () => ({
  speechRecognitionSupported: false,
  useVoiceInput: () => ({ listening: false, toggleListening: vi.fn() }),
}))

vi.mock('../hooks/useTTS', () => ({
  ttsSupported: false,
  useTTS: () => ({ speakingId: null, speak: vi.fn(), stop: vi.fn() }),
  useAvailableVoices: () => [],
  getStoredVoiceURI: () => null,
  setStoredVoiceURI: vi.fn(),
}))

import { ChatPanel } from '../components/ChatPanel'

beforeEach(() => {
  mockStore.sendMessage = vi.fn()
  mockStore.fetchOlderMessages = vi.fn()
  mockStore.messages = []
  mockStore.chatLoading = false
  mockStore.historyLoading = false
  mockStore.hasMoreHistory = false
  mockClearChatPrefill.mockReset()
})

describe('ChatPanel', () => {
  it('renders onboarding empty state for new users (no things)', () => {
    render(<ChatPanel />)
    expect(screen.getByText(/Welcome! I'm Reli/)).toBeInTheDocument()
  })

  it('renders empty state prompt for returning users (has things)', () => {
    mockStore.things = [{}]
    render(<ChatPanel />)
    expect(screen.getByText("What's on your mind?")).toBeInTheDocument()
  })

  it('renders messages', () => {
    mockStore.messages = [
      {
        id: '1',
        session_id: 's',
        role: 'user',
        content: 'Hello there',
        applied_changes: null,
        questions_for_user: [],
        timestamp: '2026-01-01T12:00:00Z',
      },
      {
        id: '2',
        session_id: 's',
        role: 'assistant',
        content: 'Hi back',
        applied_changes: null,
        questions_for_user: [],
        timestamp: '2026-01-01T12:01:00Z',
      },
    ]

    render(<ChatPanel />)
    expect(screen.getByText('Hello there')).toBeInTheDocument()
    expect(screen.getByText('Hi back')).toBeInTheDocument()
  })

  it('send button is disabled when input is empty', () => {
    render(<ChatPanel />)
    const btn = screen.getByTitle('Send (Enter)')
    expect(btn).toBeDisabled()
  })

  it('calls sendMessage when send button is clicked', () => {
    mockStore.sendMessage = vi.fn().mockResolvedValue(undefined)

    render(<ChatPanel />)
    const textarea = screen.getByPlaceholderText('Message Reli…')
    fireEvent.change(textarea, { target: { value: 'test message' } })

    const btn = screen.getByTitle('Send (Enter)')
    expect(btn).not.toBeDisabled()
    fireEvent.click(btn)

    expect(mockStore.sendMessage).toHaveBeenCalledWith('test message')
  })

  it('send button is disabled when chatLoading is true', () => {
    mockStore.chatLoading = true
    render(<ChatPanel />)
    const btn = screen.getByTitle('Send (Enter)')
    expect(btn).toBeDisabled()
  })

  it('hides empty state while history is loading', () => {
    mockStore.historyLoading = true
    mockStore.hasMoreHistory = true
    render(<ChatPanel />)
    expect(screen.queryByText("What's on your mind?")).not.toBeInTheDocument()
  })

  it('renders NudgeBanner when nudges are present', () => {
    mockStore.nudges = [{
      id: 'proactive_abc_birthday',
      nudge_type: 'approaching_date',
      message: 'Test nudge message',
      thing_id: 'abc',
      thing_title: 'Test',
      thing_type_hint: null,
      days_away: 1,
      primary_action_label: null,
    }]
    render(<ChatPanel />)
    expect(screen.getByText('Test nudge message')).toBeInTheDocument()
    mockStore.nudges = []
  })

  it('renders context dropdown pills when messages have context things', () => {
    mockStore.messages = [
      {
        id: '1',
        session_id: 's',
        role: 'assistant',
        content: 'I referenced some things.',
        applied_changes: {
          context_things: [{ id: 'ctx-1', title: 'Auth Refactor', type_hint: 'task' }],
          referenced_things: [],
        } as never,
        questions_for_user: [],
        timestamp: '2026-01-01T12:00:00Z',
      },
    ]
    render(<ChatPanel />)
    expect(screen.getByTestId('pill-inferred')).toBeInTheDocument()
    expect(screen.queryByText('Auth Refactor')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('▾ details'))
    expect(screen.getByText('Auth Refactor')).toBeInTheDocument()
    mockStore.messages = []
  })

  it('populates textarea from chatPrefill and clears it', async () => {
    mockStore.chatPrefill = 'Let\'s talk about "Write proposal"'
    render(<ChatPanel />)
    const textarea = screen.getByPlaceholderText('Message Reli…')
    await waitFor(() => {
      expect(textarea).toHaveValue('Let\'s talk about "Write proposal"')
    })
    expect(mockClearChatPrefill).toHaveBeenCalledTimes(1)
    mockStore.chatPrefill = null
  })

  it('shows Briefing badge for morning_briefing session', () => {
    mockStore.sessions = [{ id: 'sess-1', title: 'Morning briefing', origin: 'morning_briefing', created_at: '', last_active_at: '' }]
    mockStore.sessionId = 'sess-1'
    render(<ChatPanel />)
    expect(screen.getByText('📋 Briefing')).toBeInTheDocument()
    expect(screen.getByText('Morning briefing')).toBeInTheDocument()
    mockStore.sessions = []
    mockStore.sessionId = ''
  })

  it('shows Weekly badge for weekly_review session', () => {
    mockStore.sessions = [{ id: 'sess-2', title: 'Weekly review', origin: 'weekly_review', created_at: '', last_active_at: '' }]
    mockStore.sessionId = 'sess-2'
    render(<ChatPanel />)
    expect(screen.getByText('📅 Weekly')).toBeInTheDocument()
    mockStore.sessions = []
    mockStore.sessionId = ''
  })

  it('shows fallback subtitle when no active session', () => {
    mockStore.sessions = []
    mockStore.sessionId = ''
    render(<ChatPanel />)
    expect(screen.getByText('Your personal knowledge companion')).toBeInTheDocument()
  })
})
