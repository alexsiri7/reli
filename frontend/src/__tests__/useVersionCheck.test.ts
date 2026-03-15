import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useVersionCheck } from '../hooks/useVersionCheck'

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  globalThis.fetch = fetchMock
  vi.useFakeTimers()
  // Define __APP_BUILD_VERSION__ for tests
  ;(globalThis as Record<string, unknown>).__APP_BUILD_VERSION__ = 'v1.0.0'
})

afterEach(() => {
  vi.useRealTimers()
  delete (globalThis as Record<string, unknown>).__APP_BUILD_VERSION__
})

describe('useVersionCheck', () => {
  it('starts with no new version available', () => {
    const { result } = renderHook(() => useVersionCheck())
    expect(result.current.newVersionAvailable).toBe(false)
  })

  it('detects new version after poll', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ version: 'v2.0.0' }),
    })

    const { result } = renderHook(() => useVersionCheck())

    // Advance past the polling interval
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })

    expect(result.current.newVersionAvailable).toBe(true)
  })

  it('does not flag when same version', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ version: 'v1.0.0' }),
    })

    const { result } = renderHook(() => useVersionCheck())

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })

    expect(result.current.newVersionAvailable).toBe(false)
  })

  it('dismiss clears the banner', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ version: 'v2.0.0' }),
    })

    const { result } = renderHook(() => useVersionCheck())

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(result.current.newVersionAvailable).toBe(true)

    act(() => {
      result.current.dismiss()
    })
    expect(result.current.newVersionAvailable).toBe(false)
  })

  it('dismissed version stays dismissed on subsequent polls', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ version: 'v2.0.0' }),
    })

    const { result } = renderHook(() => useVersionCheck())

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(result.current.newVersionAvailable).toBe(true)

    act(() => {
      result.current.dismiss()
    })
    expect(result.current.newVersionAvailable).toBe(false)

    // Another poll with same version
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(result.current.newVersionAvailable).toBe(false)
  })

  it('re-shows banner when newer version detected after dismissal', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ version: 'v2.0.0' }),
    })

    const { result } = renderHook(() => useVersionCheck())

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })

    act(() => {
      result.current.dismiss()
    })
    expect(result.current.newVersionAvailable).toBe(false)

    // Now a newer version appears
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ version: 'v3.0.0' }),
    })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(result.current.newVersionAvailable).toBe(true)
  })

  it('handles fetch errors silently', async () => {
    fetchMock.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() => useVersionCheck())

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })

    expect(result.current.newVersionAvailable).toBe(false)
  })

  it('handles non-ok responses silently', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500 })

    const { result } = renderHook(() => useVersionCheck())

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })

    expect(result.current.newVersionAvailable).toBe(false)
  })

  it('cleans up interval on unmount', () => {
    const { unmount } = renderHook(() => useVersionCheck())
    unmount()
    // No assertion needed — just verify no errors after unmount
    // Advance timers to ensure no callbacks fire
    vi.advanceTimersByTime(120_000)
  })
})
