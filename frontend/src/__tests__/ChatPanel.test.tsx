import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

type Msg = {
  id: string | number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  applied_changes: null
  timestamp: string
  streaming?: boolean
}

const mockStore = {
  messages: [] as Msg[],
  chatLoading: false,
  sendMessage: vi.fn(),
}

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockStore) => unknown) => selector(mockStore),
}))

import { ChatPanel } from '../components/ChatPanel'

beforeEach(() => {
  mockStore.sendMessage = vi.fn()
  mockStore.messages = []
  mockStore.chatLoading = false
})

describe('ChatPanel', () => {
  it('renders empty state prompt', () => {
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
        timestamp: '2026-01-01T12:00:00Z',
      },
      {
        id: '2',
        session_id: 's',
        role: 'assistant',
        content: 'Hi back',
        applied_changes: null,
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
})
