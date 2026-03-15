import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'

const mockStore: Record<string, unknown> = {
  fetchThings: vi.fn(),
  fetchBriefing: vi.fn(),
}

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockStore) => unknown) => selector(mockStore),
}))

let mockNetworkStatus = { isOnline: true, wasOffline: false }

vi.mock('../hooks/useNetworkStatus', () => ({
  useNetworkStatus: () => mockNetworkStatus,
}))

let mockPendingCount = 0

vi.mock('../offline/pending-ops', () => ({
  getPendingCount: () => Promise.resolve(mockPendingCount),
}))

const mockInitSyncEngine = vi.fn(() => vi.fn())
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const mockOnSyncEvent = vi.fn((_cb: (event: { type: string; remaining?: number }) => void) => {
  return vi.fn()
})

vi.mock('../offline/sync-engine', () => ({
  initSyncEngine: () => mockInitSyncEngine(),
  onSyncEvent: (cb: (event: { type: string; remaining?: number }) => void) => mockOnSyncEvent(cb),
}))

import { OfflineIndicator } from '../components/OfflineIndicator'

beforeEach(() => {
  mockNetworkStatus = { isOnline: true, wasOffline: false }
  mockPendingCount = 0
  mockInitSyncEngine.mockClear()
  mockOnSyncEvent.mockClear()
  ;(mockStore.fetchThings as ReturnType<typeof vi.fn>).mockClear()
  ;(mockStore.fetchBriefing as ReturnType<typeof vi.fn>).mockClear()
})

async function renderAndFlush(networkStatus: { isOnline: boolean; wasOffline: boolean }, pending: number) {
  mockNetworkStatus = networkStatus
  mockPendingCount = pending
  const result = render(<OfflineIndicator />)
  // Flush the initial getPendingCount() promise
  await act(async () => {
    await Promise.resolve()
  })
  return result
}

describe('OfflineIndicator', () => {
  it('renders nothing when online and never was offline', async () => {
    const { container } = await renderAndFlush({ isOnline: true, wasOffline: false }, 0)
    expect(container.textContent).toBe('')
  })

  it('shows "Back online" when was offline with no pending changes', async () => {
    await renderAndFlush({ isOnline: true, wasOffline: true }, 0)
    expect(screen.getByText('Back online')).toBeInTheDocument()
  })

  it('shows "Back online — syncing N changes" when was offline with pending ops', async () => {
    await renderAndFlush({ isOnline: true, wasOffline: true }, 3)
    expect(screen.getByText(/Back online — syncing 3 changes/)).toBeInTheDocument()
  })

  it('shows singular "change" for 1 pending op', async () => {
    await renderAndFlush({ isOnline: true, wasOffline: true }, 1)
    expect(screen.getByText(/syncing 1 change…/)).toBeInTheDocument()
  })

  it('shows "Offline" when not online', async () => {
    await renderAndFlush({ isOnline: false, wasOffline: false }, 0)
    expect(screen.getByText('Offline')).toBeInTheDocument()
  })

  it('shows pending count when offline with queued changes', async () => {
    await renderAndFlush({ isOnline: false, wasOffline: false }, 5)
    expect(screen.getByText(/Offline — 5 changes will sync when online/)).toBeInTheDocument()
  })

  it('initializes sync engine on mount', async () => {
    await renderAndFlush({ isOnline: true, wasOffline: false }, 0)
    expect(mockInitSyncEngine).toHaveBeenCalled()
  })

  it('subscribes to sync events', async () => {
    await renderAndFlush({ isOnline: true, wasOffline: false }, 0)
    expect(mockOnSyncEvent).toHaveBeenCalled()
  })
})
