import { useNetworkStatus } from '../hooks/useNetworkStatus'

export function OfflineIndicator() {
  const { isOnline, wasOffline } = useNetworkStatus()

  if (isOnline && !wasOffline) return null

  if (isOnline && wasOffline) {
    return (
      <div className="fixed bottom-3 left-3 z-50 flex items-center gap-1.5 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700 text-green-700 dark:text-green-300 text-xs rounded-full px-3 py-1.5 shadow animate-pulse">
        <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
        Back online
      </div>
    )
  }

  return (
    <div className="fixed bottom-3 left-3 z-50 flex items-center gap-1.5 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs rounded-full px-3 py-1.5 shadow">
      <span className="inline-block w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
      Offline
    </div>
  )
}
