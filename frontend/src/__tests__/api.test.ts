import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { apiFetch } from '../api'

const mockFetchCurrentUser = vi.fn()

vi.mock('../store', () => ({
  useStore: {
    getState: () => ({ fetchCurrentUser: mockFetchCurrentUser }),
  },
}))

beforeEach(() => {
  vi.restoreAllMocks()
  mockFetchCurrentUser.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch', () => {
  it('passes credentials: same-origin to fetch', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ status: 200, ok: true })
    vi.stubGlobal('fetch', mockFetch)

    await apiFetch('/api/things')

    expect(mockFetch).toHaveBeenCalledWith('/api/things', { credentials: 'same-origin' })
  })

  it('merges init options with credentials', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ status: 200, ok: true })
    vi.stubGlobal('fetch', mockFetch)

    await apiFetch('/api/things', { method: 'POST', body: '{}' })

    expect(mockFetch).toHaveBeenCalledWith('/api/things', {
      method: 'POST',
      body: '{}',
      credentials: 'same-origin',
    })
  })

  it('returns the response from fetch', async () => {
    const mockResponse = { status: 200, ok: true, json: async () => ({ data: 1 }) }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

    const res = await apiFetch('/api/things')

    expect(res).toBe(mockResponse)
  })

  it('triggers fetchCurrentUser on 401 for non-auth endpoints', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 401, ok: false }))

    await apiFetch('/api/things')

    expect(mockFetchCurrentUser).toHaveBeenCalled()
  })

  it('does not trigger fetchCurrentUser on 401 for auth endpoints', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 401, ok: false }))

    await apiFetch('/api/auth/google')

    expect(mockFetchCurrentUser).not.toHaveBeenCalled()
  })
})
