import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { LandingPage } from '../components/LandingPage'

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('LandingPage', () => {
  it('renders sign in button(s)', () => {
    render(<LandingPage />)
    const buttons = screen.getAllByRole('button', { name: /sign in with google/i })
    expect(buttons.length).toBeGreaterThanOrEqual(1)
  })

  it('shows invite_only error when URL param is set', () => {
    vi.stubGlobal('location', {
      ...window.location,
      search: '?error=invite_only',
    })
    render(<LandingPage />)
    expect(screen.getByText(/invite-only/i)).toBeInTheDocument()
  })

  it('shows no error by default', () => {
    render(<LandingPage />)
    expect(screen.queryByText(/invite-only/i)).not.toBeInTheDocument()
  })

  it('shows "Redirecting..." while loading', async () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    render(<LandingPage />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[0])
    await waitFor(() => {
      expect(screen.getAllByText('Redirecting...').length).toBeGreaterThan(0)
    })
  })

  it('redirects to auth_url on success', async () => {
    const hrefSetter = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, href: '', search: '' },
      writable: true,
      configurable: true,
    })
    Object.defineProperty(window.location, 'href', {
      set: hrefSetter,
      configurable: true,
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ auth_url: 'https://accounts.google.com/oauth' }),
    }))
    render(<LandingPage />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[0])
    await waitFor(() => {
      expect(hrefSetter).toHaveBeenCalledWith('https://accounts.google.com/oauth')
    })
  })

  it('shows error on HTTP failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'OAuth not configured' }),
    }))
    render(<LandingPage />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[0])
    await waitFor(() => {
      expect(screen.getByText('OAuth not configured')).toBeInTheDocument()
    })
  })

  it('shows connection error on fetch failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')))
    render(<LandingPage />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[0])
    await waitFor(() => {
      expect(screen.getByText('Could not connect to server')).toBeInTheDocument()
    })
  })

  it('disables all sign-in buttons while loading', async () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    render(<LandingPage />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[0])
    for (const btn of buttons) {
      expect(btn).toBeDisabled()
    }
  })
})
