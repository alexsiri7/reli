import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'
import { DetailPanel } from './components/DetailPanel'
import { useVersionCheck } from './hooks/useVersionCheck'

function App() {
  const { fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchProactiveSurfaces, error } = useStore(
    useShallow(s => ({
      fetchThingTypes: s.fetchThingTypes,
      fetchThings: s.fetchThings,
      fetchBriefing: s.fetchBriefing,
      fetchHistory: s.fetchHistory,
      fetchDailyStats: s.fetchDailyStats,
      fetchCalendarStatus: s.fetchCalendarStatus,
      fetchProactiveSurfaces: s.fetchProactiveSurfaces,
      error: s.error,
    }))
  )

  const { newVersionAvailable, dismiss, refresh } = useVersionCheck()

  useEffect(() => {
    fetchThingTypes()
    fetchThings()
    fetchBriefing()
    fetchHistory()
    fetchDailyStats()
    fetchProactiveSurfaces()
    const interval = setInterval(() => { fetchThings(); fetchBriefing(); fetchProactiveSurfaces() }, 30_000)

    // Handle OAuth callback redirect
    const params = new URLSearchParams(window.location.search)
    if (params.has('calendar_connected') || params.has('calendar_error')) {
      // Clean up URL params
      window.history.replaceState({}, '', '/')
      fetchCalendarStatus()
    }

    return () => clearInterval(interval)
  }, [fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchProactiveSurfaces])

  return (
    <div className="flex w-full h-full overflow-hidden bg-white dark:bg-gray-900">
      {newVersionAvailable && (
        <div className="fixed top-0 left-0 right-0 z-50 flex items-center justify-center gap-3 bg-blue-600 text-white text-sm px-4 py-2 shadow-md">
          <span>A new version is available.</span>
          <button
            onClick={refresh}
            className="underline font-medium hover:text-blue-100"
          >
            Refresh to update
          </button>
          <button
            onClick={dismiss}
            className="ml-2 text-blue-200 hover:text-white text-lg leading-none"
            aria-label="Dismiss"
          >
            &times;
          </button>
        </div>
      )}
      {error && (
        <div className="fixed top-3 right-3 z-50 max-w-sm bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 text-xs rounded-lg px-3 py-2 shadow">
          ⚠ {error}
        </div>
      )}
      <Sidebar />
      <ChatPanel />
      <DetailPanel />
    </div>
  )
}

export default App
