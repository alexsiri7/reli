import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { LoginPage } from '../components/LoginPage'

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('LoginPage', () => {
  it('renders sign in button', () => {
    render(<LoginPage />)
    expect(screen.getByText('Sign in with Google')).toBeInTheDocument()
  })

  it('renders app title', () => {
    render(<LoginPage />)
    expect(screen.getByText('Reli')).toBeInTheDocument()
  })

  it('renders app description', () => {
    render(<LoginPage />)
    expect(screen.getByText('Your personal relationship manager')).toBeInTheDocument()
  })

  it('shows "Redirecting..." while loading', async () => {
    // Fetch that never resolves
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))

    render(<LoginPage />)
    fireEvent.click(screen.getByText('Sign in with Google'))

    expect(screen.getByText('Redirecting...')).toBeInTheDocument()
  })

  it('redirects to auth_url on success', async () => {
    const hrefSetter = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, href: '' },
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

    render(<LoginPage />)
    fireEvent.click(screen.getByText('Sign in with Google'))

    await waitFor(() => {
      expect(hrefSetter).toHaveBeenCalledWith('https://accounts.google.com/oauth')
    })
  })

  it('shows error on HTTP failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'OAuth not configured' }),
    }))

    render(<LoginPage />)
    fireEvent.click(screen.getByText('Sign in with Google'))

    await waitFor(() => {
      expect(screen.getByText('OAuth not configured')).toBeInTheDocument()
    })
  })

  it('shows connection error on fetch failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')))

    render(<LoginPage />)
    fireEvent.click(screen.getByText('Sign in with Google'))

    await waitFor(() => {
      expect(screen.getByText('Could not connect to server')).toBeInTheDocument()
    })
  })

  it('disables button while loading', async () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))

    render(<LoginPage />)
    const btn = screen.getByRole('button')
    fireEvent.click(btn)

    expect(btn).toBeDisabled()
  })
})
