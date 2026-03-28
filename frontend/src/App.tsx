import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'
import { DetailPanel } from './components/DetailPanel'
import GraphView from './components/GraphView'
import { LoginPage } from './components/LoginPage'
import { useVersionCheck } from './hooks/useVersionCheck'
import { OfflineIndicator } from './components/OfflineIndicator'
import { SettingsPanel } from './components/SettingsPanel'
import { FeedbackDialog } from './components/FeedbackDialog'
import { BriefingPage } from './components/BriefingPage'

function App() {
  const { currentUser, authChecked, settingsOpen, feedbackOpen, mainView, mobileView, setMobileView, fetchCurrentUser, fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchProactiveSurfaces, fetchFocusRecommendations, fetchConflictAlerts, fetchMergeSuggestions, fetchConnectionSuggestions, fetchUserSettings, fetchMorningBriefing, error } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      authChecked: s.authChecked,
      settingsOpen: s.settingsOpen,
      feedbackOpen: s.feedbackOpen,
      mainView: s.mainView,
      mobileView: s.mobileView,
      setMobileView: s.setMobileView,
      fetchCurrentUser: s.fetchCurrentUser,
      fetchThingTypes: s.fetchThingTypes,
      fetchThings: s.fetchThings,
      fetchBriefing: s.fetchBriefing,
      fetchHistory: s.fetchHistory,
      fetchDailyStats: s.fetchDailyStats,
      fetchCalendarStatus: s.fetchCalendarStatus,
      fetchProactiveSurfaces: s.fetchProactiveSurfaces,
      fetchFocusRecommendations: s.fetchFocusRecommendations,
      fetchConflictAlerts: s.fetchConflictAlerts,
      fetchMergeSuggestions: s.fetchMergeSuggestions,
      fetchConnectionSuggestions: s.fetchConnectionSuggestions,
      fetchUserSettings: s.fetchUserSettings,
      fetchMorningBriefing: s.fetchMorningBriefing,
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
    fetchFocusRecommendations()
    fetchConflictAlerts()
    fetchMergeSuggestions()
    fetchConnectionSuggestions()
    fetchUserSettings()
    fetchMorningBriefing()
    const interval = setInterval(() => { fetchThings(); fetchBriefing(); fetchProactiveSurfaces(); fetchFocusRecommendations(); fetchConflictAlerts() }, 30_000)

    // Handle OAuth callback redirect
    const params = new URLSearchParams(window.location.search)
    if (params.has('calendar_connected') || params.has('calendar_error')) {
      window.history.replaceState({}, '', '/')
      fetchCalendarStatus()
    }

    return () => clearInterval(interval)
  }, [currentUser, fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchProactiveSurfaces, fetchFocusRecommendations, fetchConflictAlerts, fetchMergeSuggestions, fetchConnectionSuggestions, fetchUserSettings, fetchMorningBriefing])

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
      {/* Desktop: side-by-side layout */}
      <div className="hidden md:contents">
        <Sidebar />
        {mainView === 'graph' ? (
          <GraphView />
        ) : mainView === 'briefing' ? (
          <BriefingPage />
        ) : (
          <>
            <DetailPanel />
            <ChatPanel />
          </>
        )}
      </div>
      {/* Mobile: show one panel at a time based on mobileView */}
      <div className="contents md:hidden">
        <div className={`flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden ${mobileView === 'things' ? '' : 'hidden'}`}>
          <Sidebar />
        </div>
        <div className={`flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden ${mobileView === 'chat' ? '' : 'hidden'}`}>
          <ChatPanel />
        </div>
        <DetailPanel />
      </div>
      {/* Mobile bottom tab bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 flex border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 safe-area-pb">
        <button
          onClick={() => setMobileView('things')}
          className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-xs font-medium transition-colors ${
            mobileView === 'things'
              ? 'text-indigo-600 dark:text-indigo-400'
              : 'text-gray-400 dark:text-gray-400'
          }`}
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm-.375 5.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
          </svg>
          Things
        </button>
        <button
          onClick={() => setMobileView('chat')}
          className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-xs font-medium transition-colors ${
            mobileView === 'chat'
              ? 'text-indigo-600 dark:text-indigo-400'
              : 'text-gray-400 dark:text-gray-400'
          }`}
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
          Chat
        </button>
      </nav>
      {settingsOpen && <SettingsPanel />}
      {feedbackOpen && <FeedbackDialog />}
    </div>
  )
}

export default App
