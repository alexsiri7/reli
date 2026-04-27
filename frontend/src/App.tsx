import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from './store'
import { Sidebar } from './components/Sidebar'
import { ChatPanel } from './components/ChatPanel'
import { DetailPanel } from './components/DetailPanel'
import { BriefingPanel } from './components/BriefingPanel'
import GraphView from './components/GraphView'
import { CalendarView } from './components/CalendarView'
import { LoginPage } from './components/LoginPage'
import { useVersionCheck } from './hooks/useVersionCheck'
import { OfflineIndicator } from './components/OfflineIndicator'
import { SettingsPanel } from './components/SettingsPanel'
import { FeedbackDialog } from './components/FeedbackDialog'
import { usePushNotifications } from './hooks/usePushNotifications'
import { PreferenceToast } from './components/PreferenceToast'
import { CommandPalette } from './components/CommandPalette'
import { QuickAdd } from './components/QuickAdd'
import { MobileFAB } from './components/MobileFAB'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'

function App() {
  const { currentUser, authChecked, settingsOpen, feedbackOpen, commandPaletteOpen, quickAddOpen, mainView, mobileView, setMobileView, rightView, fetchCurrentUser, fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchGmailStatus, fetchProactiveSurfaces, fetchFocusRecommendations, fetchConflictAlerts, fetchMergeSuggestions, fetchConnectionSuggestions, fetchUserSettings, fetchMorningBriefing, fetchNudges, fetchWeeklyBriefing, fetchChatSessions, error } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      authChecked: s.authChecked,
      settingsOpen: s.settingsOpen,
      feedbackOpen: s.feedbackOpen,
      commandPaletteOpen: s.commandPaletteOpen,
      quickAddOpen: s.quickAddOpen,
      mainView: s.mainView,
      mobileView: s.mobileView,
      setMobileView: s.setMobileView,
      rightView: s.rightView,
      fetchCurrentUser: s.fetchCurrentUser,
      fetchThingTypes: s.fetchThingTypes,
      fetchThings: s.fetchThings,
      fetchBriefing: s.fetchBriefing,
      fetchHistory: s.fetchHistory,
      fetchDailyStats: s.fetchDailyStats,
      fetchCalendarStatus: s.fetchCalendarStatus,
      fetchGmailStatus: s.fetchGmailStatus,
      fetchProactiveSurfaces: s.fetchProactiveSurfaces,
      fetchFocusRecommendations: s.fetchFocusRecommendations,
      fetchConflictAlerts: s.fetchConflictAlerts,
      fetchMergeSuggestions: s.fetchMergeSuggestions,
      fetchConnectionSuggestions: s.fetchConnectionSuggestions,
      fetchUserSettings: s.fetchUserSettings,
      fetchMorningBriefing: s.fetchMorningBriefing,
      fetchNudges: s.fetchNudges,
      fetchWeeklyBriefing: s.fetchWeeklyBriefing,
      fetchChatSessions: s.fetchChatSessions,
      error: s.error,
    }))
  )

  const { newVersionAvailable, dismiss, refresh } = useVersionCheck()
  usePushNotifications()
  useKeyboardShortcuts()

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
    fetchNudges()
    fetchWeeklyBriefing()
    fetchChatSessions()
    fetchCalendarStatus()
    fetchGmailStatus()
    const interval = setInterval(() => { fetchThings(); fetchBriefing(); fetchProactiveSurfaces(); fetchFocusRecommendations(); fetchConflictAlerts() }, 30_000)

    // Handle OAuth callback redirect
    const params = new URLSearchParams(window.location.search)
    const calendarRedirected = params.has('calendar_connected') || params.has('calendar_error')
    const gmailRedirected = params.has('gmail_connected') || params.has('gmail_error')
    if (calendarRedirected || gmailRedirected) {
      window.history.replaceState({}, '', '/')
      if (calendarRedirected) fetchCalendarStatus()
      if (gmailRedirected) fetchGmailStatus()
    }

    return () => clearInterval(interval)
  }, [currentUser, fetchThingTypes, fetchThings, fetchBriefing, fetchHistory, fetchDailyStats, fetchCalendarStatus, fetchGmailStatus, fetchProactiveSurfaces, fetchFocusRecommendations, fetchConflictAlerts, fetchMergeSuggestions, fetchConnectionSuggestions, fetchUserSettings, fetchMorningBriefing, fetchNudges, fetchWeeklyBriefing, fetchChatSessions])

  // Show nothing while checking auth
  if (!authChecked) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-canvas">
        <div className="h-8 w-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  // Show login page if not authenticated
  if (!currentUser) {
    return <LoginPage />
  }

  return (
    <div className="flex w-full h-full overflow-hidden bg-canvas">
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
        ) : mainView === 'calendar' ? (
          <CalendarView />
        ) : (
          <>
            <DetailPanel />
            {rightView === 'briefing' ? <BriefingPanel /> : <ChatPanel />}
          </>
        )}
      </div>
      {/* Mobile: show one panel at a time based on mobileView */}
      <div className="contents md:hidden">
        <div className={`flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden ${mobileView === 'things' ? '' : 'hidden'}`}>
          <Sidebar />
          {mobileView === 'things' && <MobileFAB />}
        </div>
        <div className={`flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden ${mobileView === 'chat' ? '' : 'hidden'}`}>
          <ChatPanel />
        </div>
        <div className={`flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden ${mobileView === 'briefing' ? '' : 'hidden'}`}>
          <BriefingPanel />
        </div>
        <DetailPanel />
      </div>
      {/* Mobile bottom tab bar — frosted glass with dot indicator */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 flex justify-around items-center h-20 px-8 safe-area-pb bg-canvas/80 backdrop-blur-xl shadow-[0_-10px_30px_rgba(0,0,0,0.5)]">
        <button
          onClick={() => setMobileView('things')}
          className={`relative flex flex-col items-center justify-center gap-0.5 text-[10px] font-semibold uppercase tracking-widest transition-all active:scale-90 duration-300 ease-out ${
            mobileView === 'things' ? 'text-primary' : 'text-on-surface-variant'
          }`}
        >
          {mobileView === 'things' && <span className="absolute -top-3 w-1 h-1 rounded-full bg-primary" />}
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z" />
          </svg>
          Things
        </button>
        <button
          onClick={() => setMobileView('chat')}
          className={`relative flex flex-col items-center justify-center gap-0.5 text-[10px] font-semibold uppercase tracking-widest transition-all active:scale-90 duration-300 ease-out ${
            mobileView === 'chat' ? 'text-primary' : 'text-on-surface-variant'
          }`}
        >
          {mobileView === 'chat' && <span className="absolute -top-3 w-1 h-1 rounded-full bg-primary" />}
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
          Chat
        </button>
        <button
          onClick={() => setMobileView('briefing')}
          className={`relative flex flex-col items-center justify-center gap-0.5 text-[10px] font-semibold uppercase tracking-widest transition-all active:scale-90 duration-300 ease-out ${
            mobileView === 'briefing' ? 'text-primary' : 'text-on-surface-variant'
          }`}
        >
          {mobileView === 'briefing' && <span className="absolute -top-3 w-1 h-1 rounded-full bg-primary" />}
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
          </svg>
          Briefing
        </button>
      </nav>
      {settingsOpen && <SettingsPanel />}
      {feedbackOpen && <FeedbackDialog />}
      <PreferenceToast />
      {commandPaletteOpen && <CommandPalette />}
      {quickAddOpen && <QuickAdd />}
    </div>
  )
}

export default App
