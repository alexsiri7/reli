import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

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

const mockStore = {
  messages: [] as Msg[],
  things: [] as unknown[],
  chatLoading: false,
  historyLoading: false,
  hasMoreHistory: false,
  sendMessage: vi.fn(),
  fetchOlderMessages: vi.fn(),
  sessionStats: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, api_calls: 0, cost_usd: 0, per_model: [] },
}

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockStore) => unknown) => selector(mockStore),
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
})

describe('ChatPanel', () => {
  it('renders onboarding empty state for new users (no things)', () => {
    render(<ChatPanel />)
    expect(screen.getByText('Welcome to Reli')).toBeInTheDocument()
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
})
