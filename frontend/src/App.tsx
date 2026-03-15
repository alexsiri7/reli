import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'
import { DetailPanel } from './components/DetailPanel'

function App() {
  const { fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchCalendarStatus, fetchProactiveSurfaces, error } = useStore(
    useShallow(s => ({
      fetchThingTypes: s.fetchThingTypes,
      fetchThings: s.fetchThings,
      fetchBriefing: s.fetchBriefing,
      fetchHistory: s.fetchHistory,
      fetchCalendarStatus: s.fetchCalendarStatus,
      fetchProactiveSurfaces: s.fetchProactiveSurfaces,
      error: s.error,
    }))
  )

  useEffect(() => {
    fetchThingTypes()
    fetchThings()
    fetchBriefing()
    fetchHistory()
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
  }, [fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchCalendarStatus, fetchProactiveSurfaces])

  return (
    <div className="flex w-full h-full overflow-hidden bg-white dark:bg-gray-900">
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
