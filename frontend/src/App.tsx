import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'

function App() {
  const { fetchThings, fetchHistory, fetchCalendarStatus, error } = useStore(
    useShallow(s => ({
      fetchThings: s.fetchThings,
      fetchHistory: s.fetchHistory,
      fetchCalendarStatus: s.fetchCalendarStatus,
      error: s.error,
    }))
  )

  useEffect(() => {
    fetchThings()
    fetchHistory()
    const interval = setInterval(fetchThings, 30_000)

    // Handle OAuth callback redirect
    const params = new URLSearchParams(window.location.search)
    if (params.has('calendar_connected') || params.has('calendar_error')) {
      // Clean up URL params
      window.history.replaceState({}, '', '/')
      fetchCalendarStatus()
    }

    return () => clearInterval(interval)
  }, [fetchThings, fetchHistory, fetchCalendarStatus])

  return (
    <div className="flex w-full h-full overflow-hidden bg-white dark:bg-gray-900">
      {error && (
        <div className="fixed top-3 right-3 z-50 max-w-sm bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 text-xs rounded-lg px-3 py-2 shadow">
          ⚠ {error}
        </div>
      )}
      <Sidebar />
      <ChatPanel />
    </div>
  )
}

export default App
