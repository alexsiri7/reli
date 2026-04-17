import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mockGetPendingOps = vi.fn()
const mockRemovePendingOp = vi.fn()
const mockGetDB = vi.fn()

vi.mock('../offline/pending-ops', () => ({
  getPendingOps: (...args: unknown[]) => mockGetPendingOps(...args),
  removePendingOp: (...args: unknown[]) => mockRemovePendingOp(...args),
}))

vi.mock('../offline/idb', () => ({
  getDB: (...args: unknown[]) => mockGetDB(...args),
}))

import { syncPendingOps, onSyncEvent } from '../offline/sync-engine'
import type { PendingOp } from '../offline/idb'

function makeOp(overrides: Partial<PendingOp> = {}): PendingOp {
  return {
    id: 1,
    url: '/api/things',
    method: 'POST',
    body: { title: 'test' },
    timestamp: '2026-01-01T00:00:00Z',
    status: 'pending',
    retries: 0,
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  mockGetPendingOps.mockReset()
  mockRemovePendingOp.mockReset()
  mockGetDB.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('syncPendingOps', () => {
  it('successful replay removes op and emits sync:op-ok', async () => {
    const op = makeOp()
    mockGetPendingOps.mockResolvedValue([op])
    mockRemovePendingOp.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }))

    const events: string[] = []
    const unsub = onSyncEvent(e => events.push(e.type))

    await syncPendingOps()
    unsub()

    expect(mockRemovePendingOp).toHaveBeenCalledWith(1)
    expect(events).toContain('sync:start')
    expect(events).toContain('sync:op-ok')
    expect(events).toContain('sync:done')
  })

  it('4xx response discards op as non-retryable', async () => {
    const op = makeOp()
    mockGetPendingOps.mockResolvedValue([op])
    mockRemovePendingOp.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422 }))

    const events: string[] = []
    const unsub = onSyncEvent(e => events.push(e.type))

    await syncPendingOps()
    unsub()

    expect(mockRemovePendingOp).toHaveBeenCalledWith(1)
    expect(events).toContain('sync:op-ok')
  })

  it('5xx response increments retries and emits sync:op-fail', async () => {
    const op = makeOp({ retries: 0 })
    mockGetPendingOps.mockResolvedValue([op])
    const mockPut = vi.fn().mockResolvedValue(undefined)
    mockGetDB.mockResolvedValue({ put: mockPut })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))

    const events: { type: string; error?: string }[] = []
    const unsub = onSyncEvent(e => events.push({ type: e.type, error: e.error }))

    await syncPendingOps()
    unsub()

    expect(mockPut).toHaveBeenCalledWith('pendingOps', expect.objectContaining({ retries: 1, status: 'failed' }))
    expect(mockRemovePendingOp).not.toHaveBeenCalled()
    const failEvent = events.find(e => e.type === 'sync:op-fail')
    expect(failEvent).toBeTruthy()
    expect(failEvent!.error).toContain('retry 1/3')
  })

  it('5xx after MAX_RETRIES discards op', async () => {
    const op = makeOp({ retries: 2 })
    mockGetPendingOps.mockResolvedValue([op])
    mockRemovePendingOp.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))

    const events: { type: string; error?: string }[] = []
    const unsub = onSyncEvent(e => events.push({ type: e.type, error: e.error }))

    await syncPendingOps()
    unsub()

    expect(mockRemovePendingOp).toHaveBeenCalledWith(1)
    const failEvent = events.find(e => e.type === 'sync:op-fail')
    expect(failEvent!.error).toContain('Max retries')
  })

  it('network error stops replay loop and emits sync:op-fail', async () => {
    const op1 = makeOp({ id: 1 })
    const op2 = makeOp({ id: 2 })
    mockGetPendingOps.mockResolvedValue([op1, op2])
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network offline')))

    const events: { type: string; error?: string }[] = []
    const unsub = onSyncEvent(e => events.push({ type: e.type, error: e.error }))

    await syncPendingOps()
    unsub()

    // Should only fail once (break on first network error)
    const failEvents = events.filter(e => e.type === 'sync:op-fail')
    expect(failEvents).toHaveLength(1)
    expect(failEvents[0].error).toContain('Network offline')
    expect(mockRemovePendingOp).not.toHaveBeenCalled()
  })

  it('empty queue returns immediately without emitting sync:start', async () => {
    mockGetPendingOps.mockResolvedValue([])

    const events: string[] = []
    const unsub = onSyncEvent(e => events.push(e.type))

    await syncPendingOps()
    unsub()

    expect(events).not.toContain('sync:start')
  })
})
