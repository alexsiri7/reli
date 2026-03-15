import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'
import { DetailPanel } from './components/DetailPanel'
import { LoginPage } from './components/LoginPage'
import { useVersionCheck } from './hooks/useVersionCheck'
import { OfflineIndicator } from './components/OfflineIndicator'
import { SettingsPanel } from './components/SettingsPanel'

function App() {
  const { currentUser, authChecked, settingsOpen, fetchCurrentUser, fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchProactiveSurfaces, error } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      authChecked: s.authChecked,
      settingsOpen: s.settingsOpen,
      fetchCurrentUser: s.fetchCurrentUser,
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

  // Check auth on mount
  useEffect(() => {
    fetchCurrentUser()
  }, [fetchCurrentUser])

  // Load app data once authenticated
  useEffect(() => {
    if (!currentUser) return

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
      window.history.replaceState({}, '', '/')
      fetchCalendarStatus()
    }

    return () => clearInterval(interval)
  }, [currentUser, fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchProactiveSurfaces])

  // Show nothing while checking auth
  if (!authChecked) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900">
        <div className="h-8 w-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  // Show login page if not authenticated
  if (!currentUser) {
    return <LoginPage />
  }

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
      <OfflineIndicator />
      <Sidebar />
      <ChatPanel />
      <DetailPanel />
      {settingsOpen && <SettingsPanel />}
    </div>
  )
}

export default App
