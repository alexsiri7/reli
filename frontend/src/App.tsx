import { useEffect } from 'react'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'

function App() {
  const { fetchThings, fetchBriefing, fetchHistory, error, clearError } = useStore(s => ({
    fetchThings: s.fetchThings,
    fetchBriefing: s.fetchBriefing,
    fetchHistory: s.fetchHistory,
    error: s.error,
    clearError: s.clearError,
  }))

  useEffect(() => {
    fetchThings()
    fetchBriefing()
    fetchHistory()
    const interval = setInterval(() => {
      fetchThings()
      fetchBriefing()
    }, 30_000)
    return () => clearInterval(interval)
  }, [fetchThings, fetchBriefing, fetchHistory])

  // Auto-dismiss error after 5 seconds
  useEffect(() => {
    if (!error) return
    const t = setTimeout(clearError, 5000)
    return () => clearTimeout(t)
  }, [error, clearError])

  return (
    <div className="flex w-full h-full overflow-hidden bg-white dark:bg-gray-900">
      {error && (
        <div
          role="alert"
          onClick={clearError}
          className="fixed top-3 right-3 z-50 max-w-sm bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 text-xs rounded-lg px-3 py-2 shadow cursor-pointer"
        >
          ⚠ {error}
        </div>
      )}
      <Sidebar />
      <ChatPanel />
    </div>
  )
}

export default App
