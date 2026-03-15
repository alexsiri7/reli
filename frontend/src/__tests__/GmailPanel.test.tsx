import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  globalThis.fetch = fetchMock
})

import { GmailPanel } from '../components/GmailPanel'

describe('GmailPanel', () => {
  it('shows checking state initially', () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ connected: false, email: null }) })
    render(<GmailPanel />)
    expect(screen.getByText('Checking Gmail...')).toBeInTheDocument()
  })

  it('renders nothing when gmail is not configured (501)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 501 })
    const { container } = render(<GmailPanel />)
    await waitFor(() => {
      expect(container.innerHTML).toBe('')
    })
  })

  it('shows connect button when not connected', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ connected: false, email: null }) })
    render(<GmailPanel />)
    await waitFor(() => {
      expect(screen.getByText('Connect Gmail')).toBeInTheDocument()
    })
  })

  it('shows messages when connected', async () => {
    const statusResponse = { connected: true, email: 'test@example.com' }
    const messagesResponse = [
      { id: '1', thread_id: 't1', subject: 'Test Subject', sender: 'John Doe <john@test.com>', to: 'me', date: new Date().toISOString(), snippet: 'Hello world', body: null, labels: [] },
    ]

    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve(statusResponse) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve(messagesResponse) })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
      expect(screen.getByText('Test Subject')).toBeInTheDocument()
    })
  })

  it('shows email address and disconnect button when connected', async () => {
    const statusResponse = { connected: true, email: 'user@example.com' }

    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve(statusResponse) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([]) })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText('user@example.com')).toBeInTheDocument()
      expect(screen.getByText('Disconnect')).toBeInTheDocument()
    })
  })

  it('shows no emails found when message list is empty', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ connected: true, email: 'a@b.com' }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([]) })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText('No emails found')).toBeInTheDocument()
    })
  })

  it('handles disconnect click', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ connected: true, email: 'a@b.com' }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([]) })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText('Disconnect')).toBeInTheDocument()
    })

    fetchMock.mockResolvedValueOnce({ ok: true })
    fireEvent.click(screen.getByText('Disconnect'))

    await waitFor(() => {
      expect(screen.getByText('Connect Gmail')).toBeInTheDocument()
    })
  })

  it('handles connect click and redirects', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ connected: false, email: null }) })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText('Connect Gmail')).toBeInTheDocument()
    })

    // Mock window.location.href setter
    const originalLocation = window.location
    const mockLocation = { ...originalLocation, href: '' }
    Object.defineProperty(window, 'location', { value: mockLocation, writable: true })

    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ auth_url: 'https://accounts.google.com/auth' }) })
    fireEvent.click(screen.getByText('Connect Gmail'))

    await waitFor(() => {
      expect(mockLocation.href).toBe('https://accounts.google.com/auth')
    })

    Object.defineProperty(window, 'location', { value: originalLocation, writable: true })
  })

  it('handles 401 on message fetch by showing disconnected state', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ connected: true, email: 'a@b.com' }) })
      .mockResolvedValueOnce({ ok: false, status: 401 })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText('Connect Gmail')).toBeInTheDocument()
    })
  })

  it('shows message detail when message is clicked', async () => {
    const msg = { id: '1', thread_id: 't1', subject: 'Hello', sender: 'Bob <bob@test.com>', to: 'me', date: '2026-01-15T10:00:00Z', snippet: 'Preview text', body: null, labels: [] }
    const fullMsg = { ...msg, body: 'Full email body content' }

    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ connected: true, email: 'a@b.com' }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([msg]) })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText('Hello')).toBeInTheDocument()
    })

    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve(fullMsg) })
    fireEvent.click(screen.getByText('Hello'))

    await waitFor(() => {
      expect(screen.getByText('Full email body content')).toBeInTheDocument()
      expect(screen.getByText('Back')).toBeInTheDocument()
    })
  })

  it('search form triggers message fetch with query', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ connected: true, email: 'a@b.com' }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([]) })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search emails...')).toBeInTheDocument()
    })

    const searchInput = screen.getByPlaceholderText('Search emails...')
    fireEvent.change(searchInput, { target: { value: 'test query' } })

    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([]) })
    fireEvent.submit(searchInput.closest('form')!)

    await waitFor(() => {
      const calls = fetchMock.mock.calls
      const lastCall = calls[calls.length - 1]![0] as string
      expect(lastCall).toContain('q=test+query')
    })
  })

  it('shows error message on fetch failure', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ connected: true, email: 'a@b.com' }) })
      .mockResolvedValueOnce({ ok: false, status: 500 })

    render(<GmailPanel />)

    await waitFor(() => {
      expect(screen.getByText(/HTTP 500/)).toBeInTheDocument()
    })
  })
})
