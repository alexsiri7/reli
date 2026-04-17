import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mockQueueOperation = vi.fn()

vi.mock('../offline/pending-ops', () => ({
  queueOperation: (...args: unknown[]) => mockQueueOperation(...args),
}))

import { mutationFetch } from '../offline/mutation-fetch'

beforeEach(() => {
  vi.restoreAllMocks()
  mockQueueOperation.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('mutationFetch', () => {
  it('online: delegates to real fetch and returns actual response', async () => {
    Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
    const mockResponse = { status: 200, ok: true }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

    const res = await mutationFetch('/api/things', { method: 'POST', body: '{"title":"test"}' })

    expect(res).toBe(mockResponse)
    expect(mockQueueOperation).not.toHaveBeenCalled()
  })

  it('offline: queues operation with parsed body', async () => {
    Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })
    mockQueueOperation.mockResolvedValue(1)

    const res = await mutationFetch('/api/things', { method: 'POST', body: '{"title":"test"}' })

    expect(mockQueueOperation).toHaveBeenCalledWith('/api/things', 'POST', { title: 'test' })
    expect(res.status).toBe(202)
    const body = await res.json()
    expect(body).toEqual({ queued: true })
  })

  it('offline: queues raw string body when JSON parse fails', async () => {
    Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })
    mockQueueOperation.mockResolvedValue(1)

    await mutationFetch('/api/things', { method: 'POST', body: 'not json' })

    expect(mockQueueOperation).toHaveBeenCalledWith('/api/things', 'POST', 'not json')
  })

  it('offline: synthetic response has correct headers and status', async () => {
    Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })
    mockQueueOperation.mockResolvedValue(1)

    const res = await mutationFetch('/api/things', { method: 'PUT', body: '{}' })

    expect(res.status).toBe(202)
    expect(res.headers.get('Content-Type')).toBe('application/json')
  })
})
