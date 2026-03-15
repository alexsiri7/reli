import { useState, useEffect } from 'react'
import { useNetworkStatus } from '../hooks/useNetworkStatus'
import { getPendingCount } from '../offline/pending-ops'
import { onSyncEvent, initSyncEngine } from '../offline/sync-engine'
import { useStore } from '../store'

export function OfflineIndicator() {
  const { isOnline, wasOffline } = useNetworkStatus()
  const [pendingCount, setPendingCount] = useState(0)
  const fetchThings = useStore(s => s.fetchThings)
  const fetchBriefing = useStore(s => s.fetchBriefing)

  // Initialize sync engine once and subscribe to sync events
  useEffect(() => {
    const cleanupSync = initSyncEngine()

    // Load initial count
    getPendingCount().then(setPendingCount)

    // Update count on sync events
    const cleanupListener = onSyncEvent((event) => {
      if (event.remaining !== undefined) {
        setPendingCount(event.remaining)
      }
      if (event.type === 'sync:done') {
        // Re-read from IDB for accuracy after sync completes
        getPendingCount().then(setPendingCount)
        // Refresh store data after sync replays queued mutations
        fetchThings()
        fetchBriefing()
      }
    })

    // Poll count periodically while offline (ops may be queued from elsewhere)
    const interval = setInterval(() => {
      getPendingCount().then(setPendingCount)
    }, 5000)

    return () => {
      cleanupSync()
      cleanupListener()
      clearInterval(interval)
    }
  }, [fetchThings, fetchBriefing])

  if (isOnline && !wasOffline && pendingCount === 0) return null

  if (isOnline && wasOffline) {
    return (
      <div className="fixed bottom-3 left-3 z-50 flex items-center gap-1.5 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700 text-green-700 dark:text-green-300 text-xs rounded-full px-3 py-1.5 shadow animate-pulse">
        <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
        {pendingCount > 0
          ? `Back online — syncing ${pendingCount} change${pendingCount === 1 ? '' : 's'}…`
          : 'Back online'}
      </div>
    )
  }

  if (!isOnline) {
    return (
      <div className="fixed bottom-3 left-3 z-50 flex items-center gap-1.5 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs rounded-full px-3 py-1.5 shadow">
        <span className="inline-block w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
        {pendingCount > 0
          ? `Offline — ${pendingCount} change${pendingCount === 1 ? '' : 's'} will sync when online`
          : 'Offline'}
      </div>
    )
  }

  return null
}
