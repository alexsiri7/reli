import { create } from 'zustand'
import { apiFetch, BASE } from './api'
import { setTheme as applyTheme } from './hooks/useTheme'
import {
  cacheThings, getCachedThings,
  cacheThingTypes, getCachedThingTypes,
  cacheRelationships, getCachedRelationships,
  cacheBriefing, getCachedBriefing,
  cacheCalendarEvents, getCachedCalendarEvents,
} from './offline/cache'
import { getByKey } from './offline/idb'
import { mutationFetch } from './offline/mutation-fetch'
import { simpleFetch } from './store-fetch'
import { executeSendMessage } from './send-message'
import {
  validateResponse,
  ThingSchema,
  ThingTypeSchema,
  RelationshipSchema,
  AuthUserSchema,
  BriefingResponseSchema,
  ProactiveSurfaceSchema,
  FocusResponseSchema,
  ChatMessageSchema,
  SessionStatsSchema,
  CalendarStatusSchema,
  GmailStatusSchema,
  CalendarEventSchema,
  ModelSettingsSchema,
  UserSettingsSchema,
  RequestyModelSchema,
  UserProfileSchema,
  MergeSuggestionSchema,
  MergeResultSchema,
  ConnectionSuggestionSchema,
  ConflictAlertSchema,
  MorningBriefingSchema,
  BriefingPreferencesSchema,
} from './schemas'
import { z } from 'zod'

import type {
  Thing,
  ThingType,
  Relationship,
  RequestyModel,
  ProactiveSurface,
  FocusRecommendation,
  ConflictAlert,
  SweepFinding,
  LearnedPreference,
  MorningBriefing,
  BriefingPreferences,
  WeeklyBriefing,
  ModelSettings,
  UserSettings,
  UserProfile,
  MergeSuggestion,
  ConnectionSuggestion,
} from './generated/api-types'

import type {
  AuthUser, BriefingItem, BriefingStats, CalendarEvent, CalendarStatus,
  ChatMessage, ChatMode, ChatSession, GmailStatus, InteractionStyle,
  Nudge, SessionStats,
} from './types'

export interface ReliState {
  currentUser: AuthUser | null
  authChecked: boolean
  fetchCurrentUser: () => Promise<void>
  logout: () => Promise<void>
  thingTypes: ThingType[]
  things: Thing[]
  briefing: Thing[]
  theOneThing: BriefingItem | null
  secondaryItems: BriefingItem[]
  briefingStats: BriefingStats | null
  findings: SweepFinding[]
  learnedPreferences: LearnedPreference[]
  messages: ChatMessage[]
  sessionId: string
  chatSessions: ChatSession[]
  chatSessionsLoading: boolean
  sessionStats: SessionStats
  loading: boolean
  chatLoading: boolean
  historyLoading: boolean
  hasMoreHistory: boolean
  error: string | null
  calendarStatus: CalendarStatus
  calendarEvents: CalendarEvent[]
  gmailStatus: GmailStatus

  morningBriefing: MorningBriefing | null
  morningBriefingLoading: boolean
  briefingPreferences: BriefingPreferences | null
  fetchMorningBriefing: () => Promise<void>
  fetchBriefingPreferences: () => Promise<void>
  updateBriefingPreferences: (prefs: BriefingPreferences) => Promise<void>

  nudges: Nudge[]
  nudgesLoading: boolean
  fetchNudges: () => Promise<void>
  dismissNudge: (nudgeId: string) => Promise<void>
  stopNudgeType: (nudgeId: string) => Promise<void>

  weeklyBriefing: WeeklyBriefing | null
  weeklyBriefingLoading: boolean
  fetchWeeklyBriefing: () => Promise<void>

  proactiveSurfaces: ProactiveSurface[]
  focusRecommendations: FocusRecommendation[]
  focusLoading: boolean
  focusCalendarActive: boolean
  fetchFocusRecommendations: () => Promise<void>
  conflictAlerts: ConflictAlert[]
  searchResults: Thing[]
  searchLoading: boolean
  searchThings: (query: string) => Promise<void>
  clearSearch: () => void

  // Detail panel
  detailThingId: string | null
  detailHistory: string[]
  detailThing: Thing | null
  detailRelationships: Relationship[]
  detailLoading: boolean
  openThingDetail: (id: string) => void
  navigateThingDetail: (id: string) => void
  goBackThingDetail: () => void
  closeThingDetail: () => void
  fetchDailyStats: () => Promise<void>
  fetchThingTypes: () => Promise<void>
  fetchThings: () => Promise<void>
  fetchBriefing: () => Promise<void>
  fetchProactiveSurfaces: () => Promise<void>
  fetchConflictAlerts: () => Promise<void>
  dismissFinding: (findingId: string) => Promise<void>
  snoozeFinding: (findingId: string, until: string) => Promise<void>
  actOnFinding: (finding: SweepFinding) => void
  snoozeThing: (id: string, checkinDate: string | null) => Promise<void>
  updateThing: (id: string, updates: Record<string, unknown>) => Promise<void>
  continueInChat: (briefingText: string, sessionTitle: string, origin: 'morning_briefing' | 'weekly_review', openingMessage: string) => Promise<void>
  chatPrefill: string | null
  openChatWithContext: (thingId: string, title: string) => void
  clearChatPrefill: () => void
  fetchHistory: () => Promise<void>
  fetchOlderMessages: () => Promise<void>
  sendMessage: (text: string) => Promise<void>
  fetchChatSessions: () => Promise<void>
  createChatSession: (title?: string) => Promise<string>
  switchChatSession: (sessionId: string) => Promise<void>
  renameChatSession: (sessionId: string, title: string) => Promise<void>
  deleteChatSession: (sessionId: string) => Promise<void>
  deleteMessage: (sessionId: string, messageId: number) => Promise<void>
  clearError: () => void
  fetchCalendarStatus: () => Promise<void>
  fetchGmailStatus: () => Promise<void>
  fetchCalendarEvents: () => Promise<void>
  connectCalendar: () => Promise<void>
  disconnectCalendar: () => Promise<void>

  // Google seed (onboarding)
  googleSeedLoading: boolean
  seedFromGoogle: () => Promise<{ count: number }>

  // Things list filter (client-side, persists across panel switches)
  thingFilterQuery: string
  thingFilterTypes: string[]
  setThingFilterQuery: (query: string) => void
  toggleThingFilterType: (type: string) => void
  clearThingFilters: () => void

  // View mode
  mainView: 'list' | 'graph' | 'calendar'
  setMainView: (view: 'list' | 'graph' | 'calendar') => void

  // Chat mode (Hats)
  chatMode: ChatMode
  setChatMode: (mode: ChatMode) => void

  // Interaction style (Coach vs Consultant)
  interactionStyle: InteractionStyle
  setInteractionStyle: (style: InteractionStyle) => void

  // Mobile navigation
  mobileView: 'things' | 'chat' | 'briefing'
  setMobileView: (view: 'things' | 'chat' | 'briefing') => void

  // Right panel view (desktop)
  rightView: 'chat' | 'briefing'
  setRightView: (view: 'chat' | 'briefing') => void

  // Settings
  settingsOpen: boolean
  modelSettings: ModelSettings | null
  userSettings: UserSettings | null
  availableModels: RequestyModel[]
  settingsLoading: boolean
  modelsLoading: boolean
  openSettings: () => void
  closeSettings: () => void
  fetchModelSettings: () => Promise<void>
  fetchAvailableModels: () => Promise<void>
  updateModelSettings: (settings: Partial<ModelSettings>) => Promise<void>
  fetchUserSettings: () => Promise<void>
  updateUserSettings: (settings: Partial<UserSettings>) => Promise<void>

  // User profile
  userProfile: UserProfile | null
  userProfileLoading: boolean
  fetchUserProfile: () => Promise<void>
  updateUserThing: (updates: { title?: string; data?: Record<string, unknown> }) => Promise<void>

  // Merge suggestions
  mergeSuggestions: MergeSuggestion[]
  mergeSuggestionsLoading: boolean
  mergeInProgress: boolean
  fetchMergeSuggestions: () => Promise<void>
  executeMerge: (keepId: string, removeId: string) => Promise<void>
  dismissMergeSuggestion: (thingAId: string, thingBId: string) => void

  // Connection suggestions
  connectionSuggestions: ConnectionSuggestion[]
  connectionSuggestionsLoading: boolean
  connectionAcceptInProgress: boolean
  fetchConnectionSuggestions: () => Promise<void>
  acceptConnectionSuggestion: (id: string, relationshipType?: string) => Promise<void>
  dismissConnectionSuggestion: (id: string) => Promise<void>
  deferConnectionSuggestion: (id: string) => Promise<void>

  // Preference toasts
  preferenceToasts: { id: string; title: string; confidenceLabel: string; action: 'created' | 'updated' }[]
  dismissPreferenceToast: (id: string) => void

  // Preference feedback
  submitPreferenceFeedback: (thingId: string, accurate: boolean) => Promise<void>

  // Feedback
  feedbackOpen: boolean
  openFeedback: () => void
  closeFeedback: () => void
  submitFeedback: (data: {
    category: string
    message: string
    user_agent: string
    url: string
    screenshot_base64?: string
  }) => Promise<{ success: boolean; issueUrl?: string; error?: string }>

  // Keyboard shortcuts — command palette
  commandPaletteOpen: boolean
  openCommandPalette: () => void
  closeCommandPalette: () => void

  // Keyboard shortcuts — quick add
  quickAddOpen: boolean
  openQuickAdd: () => void
  closeQuickAdd: () => void

  // Sidebar visibility (desktop)
  sidebarOpen: boolean
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void

  // toggleRightView alias
  toggleRightView: () => void

  // Create a Thing directly (quick add)
  createThing: (title: string, typeHint?: string, checkinDate?: string) => Promise<Thing>

  // Chat input focus (registered by ChatPanel)
  _chatInputFocusFn: (() => void) | null
  registerChatInputFocus: (fn: () => void) => void
  focusChatInput: () => void
}

const HISTORY_PAGE_SIZE = 20

const LEGACY_SESSION_KEY = 'reli-session-id'

function getLegacySessionId(): string | null {
  return localStorage.getItem(LEGACY_SESSION_KEY)
}

async function fetchThingDetailWithFallback(
  id: string,
): Promise<[Thing | null, Relationship[]]> {
  try {
    const [thing, rels] = await Promise.all([
      apiFetch(`${BASE}/things/${id}`).then(r => r.ok ? r.json().then(d => validateResponse(ThingSchema, d, `/things/${id}`)) : null),
      apiFetch(`${BASE}/things/${id}/relationships`).then(r => r.ok ? r.json().then(d => validateResponse(z.array(RelationshipSchema), d, `/things/${id}/relationships`)) : []),
    ])
    if (rels.length > 0) cacheRelationships(rels).catch(() => {})
    return [thing, rels]
  } catch {
    if (!navigator.onLine) {
      const [thing, rels] = await Promise.all([
        getByKey('things', id).catch(() => undefined),
        getCachedRelationships(id).catch(() => []),
      ])
      return [thing ?? null, rels]
    }
    throw new Error('Network error')
  }
}

function loadAndSetDetail(
  id: string,
  get: () => ReliState,
  set: (partial: Partial<ReliState>) => void,
) {
  fetchThingDetailWithFallback(id).then(([thing, rels]) => {
    if (get().detailThingId === id) {
      set({ detailThing: thing, detailRelationships: rels, detailLoading: false })
    }
  }).catch(() => {
    if (get().detailThingId === id) set({ detailLoading: false })
  })
}

export const useStore = create<ReliState>((set, get) => ({
  currentUser: null,
  authChecked: false,

  fetchCurrentUser: async () => {
    try {
      const res = await apiFetch(`${BASE}/auth/me`)
      if (res.ok) {
        const user: AuthUser = validateResponse(AuthUserSchema, await res.json(), '/auth/me')
        set({ currentUser: user, authChecked: true, sessionId: user.id })

        // Migrate legacy random session ID to user-based session ID
        const legacyId = getLegacySessionId()
        if (legacyId && legacyId !== user.id) {
          apiFetch(`${BASE}/chat/migrate-session`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_session_id: legacyId, new_session_id: user.id }),
          }).then(() => {
            localStorage.removeItem(LEGACY_SESSION_KEY)
          }).catch(() => {
            // Migration is best-effort; old history may be orphaned
          })
        }

        // Load chat sessions and restore last active session
        await get().fetchChatSessions()
        const savedSessionId = localStorage.getItem('reli-active-session')
        if (savedSessionId) {
          const sessions = get().chatSessions
          if (sessions.some(s => s.id === savedSessionId)) {
            set({ sessionId: savedSessionId })
          }
        }
      } else {
        set({ currentUser: null, authChecked: true })
      }
    } catch {
      set({ currentUser: null, authChecked: true })
    }
  },

  logout: async () => {
    try {
      await apiFetch(`${BASE}/auth/logout`, { method: 'POST' })
    } catch {
      // ignore
    }
    set({ currentUser: null })
    window.location.href = '/'
  },

  thingTypes: [],
  things: [],
  briefing: [],
  theOneThing: null,
  secondaryItems: [],
  briefingStats: null,
  findings: [],
  learnedPreferences: [],
  messages: [],
  sessionId: '',
  chatSessions: [],
  chatSessionsLoading: false,
  sessionStats: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, api_calls: 0, cost_usd: 0, per_model: [] },
  loading: false,
  chatLoading: false,
  historyLoading: false,
  hasMoreHistory: true,
  error: null,
  calendarStatus: { configured: false, connected: false },
  calendarEvents: [],
  gmailStatus: { connected: false, email: null },
  morningBriefing: null,
  morningBriefingLoading: false,
  chatPrefill: null,
  briefingPreferences: null,

  nudges: [],
  nudgesLoading: false,
  weeklyBriefing: null,
  weeklyBriefingLoading: false,

  fetchMorningBriefing: () => simpleFetch('/briefing/morning', MorningBriefingSchema, 'morningBriefing', 'morningBriefingLoading')(set),

  fetchBriefingPreferences: () => simpleFetch('/briefing/preferences', BriefingPreferencesSchema, 'briefingPreferences')(set),

  updateBriefingPreferences: async (prefs: BriefingPreferences) => {
    try {
      const res = await apiFetch(`${BASE}/briefing/preferences`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(prefs),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = validateResponse(BriefingPreferencesSchema, await res.json(), '/briefing/preferences')
      set({ briefingPreferences: data })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchNudges: async () => {
    set({ nudgesLoading: true })
    try {
      const res = await apiFetch(`${BASE}/nudges`)
      if (!res.ok) return
      const data = await res.json()
      if (Array.isArray(data)) set({ nudges: data })
    } catch {
      // best-effort
    } finally {
      set({ nudgesLoading: false })
    }
  },

  dismissNudge: async (nudgeId: string) => {
    set(s => ({ nudges: s.nudges.filter(n => n.id !== nudgeId) }))
    try {
      await apiFetch(`${BASE}/nudges/${nudgeId}/dismiss`, { method: 'POST' })
    } catch {
      // best-effort
    }
  },

  stopNudgeType: async (nudgeId: string) => {
    set(s => ({ nudges: s.nudges.filter(n => n.id !== nudgeId) }))
    try {
      const res = await apiFetch(`${BASE}/nudges/${nudgeId}/stop`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        if (data?.preference) {
          set(s => ({
            preferenceToasts: [...s.preferenceToasts, {
              id: `pref-toast-${Date.now()}-${data.preference.id}`,
              title: data.preference.title,
              confidenceLabel: data.preference.confidence_label,
              action: data.preference.action,
            }],
          }))
          get().fetchBriefing()
        }
      }
    } catch {
      // best-effort
    }
  },

  fetchWeeklyBriefing: async () => {
    set({ weeklyBriefingLoading: true })
    try {
      const res = await apiFetch(`${BASE}/briefing/weekly`)
      if (!res.ok) return
      const data = await res.json()
      set({ weeklyBriefing: data })
    } catch {
      // best-effort
    } finally {
      set({ weeklyBriefingLoading: false })
    }
  },

  proactiveSurfaces: [],
  focusRecommendations: [],
  focusLoading: false,
  focusCalendarActive: false,
  conflictAlerts: [],
  searchResults: [],
  searchLoading: false,

  // Detail panel
  detailThingId: null,
  detailHistory: [],
  detailThing: null,
  detailRelationships: [],
  detailLoading: false,

  openThingDetail: (id: string) => {
    set({ detailThingId: id, detailHistory: [], detailLoading: true, detailThing: null, detailRelationships: [] })
    loadAndSetDetail(id, get, set)
  },

  navigateThingDetail: (id: string) => {
    const current = get().detailThingId
    if (!current || current === id) return
    set(s => ({
      detailThingId: id,
      detailHistory: [...s.detailHistory, current],
      detailLoading: true,
      detailThing: null,
      detailRelationships: [],
    }))
    loadAndSetDetail(id, get, set)
  },

  goBackThingDetail: () => {
    const history = get().detailHistory
    if (history.length === 0) return
    const prevId = history[history.length - 1]!
    set({ detailThingId: prevId, detailHistory: history.slice(0, -1), detailLoading: true, detailThing: null, detailRelationships: [] })
    loadAndSetDetail(prevId, get, set)
  },

  closeThingDetail: () => {
    set({ detailThingId: null, detailHistory: [], detailThing: null, detailRelationships: [], detailLoading: false })
  },

  searchThings: async (query: string) => {
    if (!query.trim()) {
      set({ searchResults: [], searchLoading: false })
      return
    }
    set({ searchLoading: true })
    try {
      const res = await apiFetch(`${BASE}/things/search?q=${encodeURIComponent(query)}&limit=50`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: Thing[] = validateResponse(z.array(ThingSchema), await res.json(), '/things/search')
      set({ searchResults: data })
    } catch {
      set({ searchResults: [] })
    } finally {
      set({ searchLoading: false })
    }
  },

  clearSearch: () => set({ searchResults: [], searchLoading: false }),

  fetchThingTypes: async () => {
    try {
      const res = await apiFetch(`${BASE}/thing-types`)
      if (!res.ok) return
      const data: ThingType[] = validateResponse(z.array(ThingTypeSchema), await res.json(), '/thing-types')
      set({ thingTypes: data })
      cacheThingTypes(data).catch(() => {})
    } catch {
      if (!navigator.onLine) {
        const cached = await getCachedThingTypes().catch(() => [])
        if (cached.length > 0) set({ thingTypes: cached })
      }
    }
  },

  fetchThings: async () => {
    set({ loading: true, error: null })
    try {
      const res = await apiFetch(`${BASE}/things?active_only=true&limit=200`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: Thing[] = validateResponse(z.array(ThingSchema), await res.json(), '/things')
      set({ things: data })
      cacheThings(data).catch(() => {})
    } catch (e) {
      if (!navigator.onLine) {
        const cached = await getCachedThings().catch(() => [])
        if (cached.length > 0) {
          set({ things: cached })
          return
        }
      }
      set({ error: String(e) })
    } finally {
      set({ loading: false })
    }
  },

  fetchBriefing: async () => {
    try {
      const res = await apiFetch(`${BASE}/briefing`)
      if (!res.ok) return
      const data = validateResponse(BriefingResponseSchema, await res.json(), '/briefing')
      const theOneThing: BriefingItem | null = data.the_one_thing ?? null
      const secondaryItems: BriefingItem[] = data.secondary ?? []
      const things: Thing[] = [
        ...(theOneThing ? [theOneThing.thing] : []),
        ...secondaryItems.map(item => item.thing),
      ]
      const findings = data.findings ?? []
      const learnedPreferences = data.learned_preferences ?? []
      const briefingStats: BriefingStats | null = data.stats ? {
        active_things: data.stats.active_things ?? 0,
        checkin_due: data.stats.checkin_due ?? 0,
        overdue: data.stats.overdue ?? 0,
      } : null
      set({ briefing: things, theOneThing, secondaryItems, briefingStats, findings, learnedPreferences })
      cacheBriefing(things, findings, learnedPreferences).catch(() => {})
    } catch {
      if (!navigator.onLine) {
        const cached = await getCachedBriefing().catch(() => undefined)
        if (cached) set({ briefing: cached.things, findings: cached.findings, learnedPreferences: cached.learnedPreferences ?? [] })
      }
    }
  },

  fetchProactiveSurfaces: async () => {
    try {
      const res = await apiFetch(`${BASE}/proactive?days=7`)
      if (!res.ok) return
      const data: ProactiveSurface[] = validateResponse(z.array(ProactiveSurfaceSchema), await res.json(), '/proactive')
      set({ proactiveSurfaces: data })
    } catch {
      // best-effort
    }
  },

  fetchFocusRecommendations: async () => {
    set({ focusLoading: true })
    try {
      const res = await apiFetch(`${BASE}/focus?limit=10`)
      if (!res.ok) return
      const data = validateResponse(FocusResponseSchema, await res.json(), '/focus')
      set({
        focusRecommendations: data.recommendations ?? [],
        focusCalendarActive: data.calendar_active ?? false,
      })
    } catch {
      // best-effort
    } finally {
      set({ focusLoading: false })
    }
  },

  fetchConflictAlerts: async () => {
    try {
      const res = await apiFetch(`${BASE}/conflicts`)
      if (!res.ok) return
      const data: ConflictAlert[] = validateResponse(z.array(ConflictAlertSchema), await res.json(), '/conflicts')
      set({ conflictAlerts: data })
    } catch {
      // best-effort
    }
  },

  dismissFinding: async (findingId: string) => {
    try {
      const res = await mutationFetch(`${BASE}/briefing/findings/${findingId}/dismiss`, { method: 'PATCH' })
      if (!res.ok && res.status !== 202) return
      set(state => ({ findings: state.findings.filter(f => f.id !== findingId) }))
    } catch {
      // ignore
    }
  },

  snoozeFinding: async (findingId: string, until: string) => {
    try {
      const res = await apiFetch(`${BASE}/briefing/findings/${findingId}/snooze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ until }),
      })
      if (!res.ok) return
      set(state => ({ findings: state.findings.filter(f => f.id !== findingId) }))
    } catch {
      // ignore
    }
  },

  actOnFinding: (finding: SweepFinding) => {
    if (finding.thing_id) {
      get().openThingDetail(finding.thing_id)
    }
  },

  /**
   * Create a new chat session pre-seeded with briefing context, then switch to it.
   *
   * Performs 3 sequential POSTs (session create, system seed, assistant seed).
   * On step 2 or 3 failure, the session row is created but partially seeded — the
   * caller sees an `error` and the orphan is left for #712-style cleanup. Only on
   * full success does the view switch to chat.
   *
   * @param briefingText    Serialised briefing content; seeded as a `system` message
   *                        that the LLM sees but the user does not (filtered in ChatPanel).
   * @param sessionTitle    Display title for the session list (e.g. "Morning briefing — 2026-04-26").
   * @param origin          Tag used for the badge in the chat header.
   * @param openingMessage  Visible assistant greeting that opens the chat.
   */
  continueInChat: async (briefingText, sessionTitle, origin, openingMessage) => {
    try {
      const sessionRes = await apiFetch(`${BASE}/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: sessionTitle, origin }),
      })
      if (!sessionRes.ok) throw new Error(`Failed to create session: ${sessionRes.status}`)
      const newSession = await sessionRes.json()
      const newSessionId: string = newSession.id

      const sysRes = await apiFetch(`${BASE}/chat/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: newSessionId, role: 'system', content: briefingText }),
      })
      if (!sysRes.ok) throw new Error(`Failed to seed system message: ${sysRes.status}`)

      const asstRes = await apiFetch(`${BASE}/chat/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: newSessionId, role: 'assistant', content: openingMessage }),
      })
      if (!asstRes.ok) throw new Error(`Failed to seed assistant message: ${asstRes.status}`)

      await get().switchChatSession(newSessionId)
      await get().fetchChatSessions()
      set({ rightView: 'chat', mobileView: 'chat' })
    } catch (e) {
      console.error('[continueInChat] failed', e)
      set({ error: 'Could not start the chat session. Please try again.' })
    }
  },
  openChatWithContext: (_thingId: string, title: string) => {
    set({
      chatPrefill: `Let's talk about "${title}"`,
      rightView: 'chat',
      mobileView: 'chat',
    })
  },
  clearChatPrefill: () => set({ chatPrefill: null }),

  snoozeThing: async (id: string, checkinDate: string | null) => {
    try {
      const res = await mutationFetch(`${BASE}/things/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkin_date: checkinDate }),
      })
      if (res.status === 202) {
        // Queued offline — optimistically update local state
        set(state => ({
          things: state.things.map(t => t.id === id ? { ...t, checkin_date: checkinDate } : t),
          briefing: state.briefing.map(t => t.id === id ? { ...t, checkin_date: checkinDate } : t),
        }))
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const updated: Thing = validateResponse(ThingSchema, await res.json(), `/things/${id}`)
      set(state => ({
        things: state.things.map(t => t.id === id ? updated : t),
        briefing: state.briefing.map(t => t.id === id ? updated : t),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  updateThing: async (id: string, updates: Record<string, unknown>) => {
    try {
      const res = await mutationFetch(`${BASE}/things/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (res.status === 202) {
        // Queued offline — optimistically update local state
        set(state => ({
          things: state.things.map(t => t.id === id ? { ...t, ...updates } as Thing : t),
          detailThing: state.detailThing?.id === id ? { ...state.detailThing, ...updates } as Thing : state.detailThing,
        }))
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const updated: Thing = validateResponse(ThingSchema, await res.json(), `/things/${id}`)
      set(state => ({
        things: state.things.map(t => t.id === id ? updated : t),
        detailThing: state.detailThing?.id === id ? updated : state.detailThing,
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchDailyStats: async () => {
    try {
      const res = await apiFetch(`${BASE}/chat/stats/today`)
      if (!res.ok) return
      const data: SessionStats = validateResponse(SessionStatsSchema, await res.json(), '/chat/stats/today')
      set({ sessionStats: data })
    } catch {
      // best-effort
    }
  },

  fetchHistory: async () => {
    set({ historyLoading: true })
    try {
      const sessionId = get().sessionId
      const res = await apiFetch(`${BASE}/chat/history/${sessionId}?limit=${HISTORY_PAGE_SIZE}`)
      if (!res.ok) return
      const data: ChatMessage[] = validateResponse(z.array(ChatMessageSchema), await res.json(), '/chat/history')
      set({
        messages: data.map(m => ({ ...m, questions_for_user: m.questions_for_user ?? [] })),
        hasMoreHistory: data.length >= HISTORY_PAGE_SIZE,
      })
    } catch {
      // ignore
    } finally {
      set({ historyLoading: false })
    }
  },

  fetchOlderMessages: async () => {
    const { messages, historyLoading, hasMoreHistory } = get()
    if (historyLoading || !hasMoreHistory) return

    const oldestMsg = messages[0]
    if (!oldestMsg || typeof oldestMsg.id !== 'number') return

    set({ historyLoading: true })
    try {
      const sessionId = get().sessionId
      const res = await apiFetch(
        `${BASE}/chat/history/${sessionId}?limit=${HISTORY_PAGE_SIZE}&before=${oldestMsg.id}`
      )
      if (!res.ok) return
      const data: ChatMessage[] = validateResponse(z.array(ChatMessageSchema), await res.json(), '/chat/history')
      set(state => ({
        messages: [...data, ...state.messages],
        hasMoreHistory: data.length >= HISTORY_PAGE_SIZE,
      }))
    } catch {
      // ignore
    } finally {
      set({ historyLoading: false })
    }
  },

  sendMessage: (text: string) => executeSendMessage(text, { set, get }),

  fetchChatSessions: async () => {
    set({ chatSessionsLoading: true })
    try {
      const res = await apiFetch(`${BASE}/chat/sessions`)
      if (!res.ok) return
      const data = await res.json()
      set({ chatSessions: data })
    } catch {
      // ignore
    } finally {
      set({ chatSessionsLoading: false })
    }
  },

  createChatSession: async (title?: string) => {
    const sessionId = crypto.randomUUID()
    try {
      const res = await apiFetch(`${BASE}/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, title: title ?? 'New chat' }),
      })
      if (!res.ok) throw new Error(await res.text())
      set({ sessionId, messages: [], hasMoreHistory: true })
      localStorage.setItem('reli-active-session', sessionId)
      await get().fetchChatSessions()
    } catch {
      // ignore
    }
    return sessionId
  },

  switchChatSession: async (sessionId: string) => {
    set({ sessionId, messages: [], hasMoreHistory: true })
    localStorage.setItem('reli-active-session', sessionId)
    await get().fetchHistory()
  },

  renameChatSession: async (sessionId: string, title: string) => {
    try {
      const res = await apiFetch(`${BASE}/chat/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      if (!res.ok) return
      set(state => ({
        chatSessions: state.chatSessions.map(s =>
          s.id === sessionId ? { ...s, title } : s
        ),
      }))
    } catch {
      // ignore
    }
  },

  deleteChatSession: async (sessionId: string) => {
    try {
      const res = await apiFetch(`${BASE}/chat/sessions/${sessionId}`, { method: 'DELETE' })
      if (!res.ok) return
      const remaining = get().chatSessions.filter(s => s.id !== sessionId)
      set({ chatSessions: remaining })
      if (get().sessionId === sessionId) {
        const first = remaining[0]
        if (first) {
          await get().switchChatSession(first.id)
        } else {
          await get().createChatSession()
        }
      }
    } catch {
      // ignore
    }
  },

  deleteMessage: async (sessionId: string, messageId: number) => {
    try {
      const res = await apiFetch(`${BASE}/chat/history/${sessionId}/${messageId}`, { method: 'DELETE' })
      if (!res.ok) return
      set(state => ({ messages: state.messages.filter(m => m.id !== messageId) }))
    } catch {
      // ignore
    }
  },

  fetchCalendarStatus: async () => {
    try {
      const res = await apiFetch(`${BASE}/calendar/status`)
      if (!res.ok) return
      const data: CalendarStatus = validateResponse(CalendarStatusSchema, await res.json(), '/calendar/status')
      set({ calendarStatus: data })
    } catch {
      // ignore
    }
  },

  fetchGmailStatus: async () => {
    try {
      const res = await apiFetch(`${BASE}/gmail/status`)
      if (!res.ok) return
      const data: GmailStatus = validateResponse(GmailStatusSchema, await res.json(), '/gmail/status')
      set({ gmailStatus: data })
    } catch {
      // ignore
    }
  },

  fetchCalendarEvents: async () => {
    try {
      const res = await apiFetch(`${BASE}/calendar/events`)
      if (!res.ok) return
      const data = await res.json()
      const events = validateResponse(z.array(CalendarEventSchema), data.events ?? [], '/calendar/events')
      set({ calendarEvents: events })
      cacheCalendarEvents(events).catch(() => {})
    } catch {
      if (!navigator.onLine) {
        const cached = await getCachedCalendarEvents().catch(() => [])
        if (cached.length > 0) set({ calendarEvents: cached })
      }
    }
  },

  connectCalendar: async () => {
    try {
      const res = await apiFetch(`${BASE}/calendar/auth`)
      if (!res.ok) return
      const data = await res.json()
      if (data.auth_url) {
        window.location.href = data.auth_url
      }
    } catch (e) {
      set({ error: String(e) })
    }
  },

  disconnectCalendar: async () => {
    try {
      const res = await apiFetch(`${BASE}/calendar/disconnect`, { method: 'DELETE' })
      if (!res.ok) return
      set({ calendarStatus: { configured: true, connected: false }, calendarEvents: [] })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  clearError: () => set({ error: null }),

  // Google seed (onboarding)
  googleSeedLoading: false,
  seedFromGoogle: async () => {
    set({ googleSeedLoading: true })
    try {
      const results = await Promise.allSettled([
        apiFetch(`${BASE}/calendar/seed`, { method: 'POST' }),
        apiFetch(`${BASE}/gmail/seed`, { method: 'POST' }),
      ])
      let count = 0
      for (const res of results) {
        if (res.status === 'fulfilled' && res.value.ok) {
          const data = await res.value.json()
          count += data.count ?? 0
        }
      }
      await get().fetchThings()
      return { count }
    } finally {
      set({ googleSeedLoading: false })
    }
  },

  // Things list filter
  thingFilterQuery: '',
  thingFilterTypes: [],
  setThingFilterQuery: (query: string) => set({ thingFilterQuery: query }),
  toggleThingFilterType: (type: string) => set(s => ({
    thingFilterTypes: s.thingFilterTypes.includes(type)
      ? s.thingFilterTypes.filter(t => t !== type)
      : [...s.thingFilterTypes, type],
  })),
  clearThingFilters: () => set({ thingFilterQuery: '', thingFilterTypes: [] }),

  // View mode
  mainView: 'list',
  setMainView: (view) => set({ mainView: view }),

  // Chat mode (Hats)
  chatMode: 'normal',
  setChatMode: (mode: ChatMode) => {
    set({ chatMode: mode })
    // Persist to user settings
    apiFetch(`${BASE}/settings/user`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_mode: mode }),
    }).catch(() => {})
  },

  // Interaction style (Coach vs Consultant)
  interactionStyle: 'auto',
  setInteractionStyle: (style: InteractionStyle) => {
    set({ interactionStyle: style })
    apiFetch(`${BASE}/settings/user`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interaction_style: style }),
    }).catch(() => {})
  },

  // Mobile navigation
  mobileView: 'briefing',
  setMobileView: (view) => set({ mobileView: view }),

  // Right panel view (desktop) — briefing is the default landing
  rightView: 'briefing',
  setRightView: (view) => set({ rightView: view }),

  // Settings
  settingsOpen: false,
  modelSettings: null,
  userSettings: null,
  availableModels: [],
  settingsLoading: false,
  modelsLoading: false,

  openSettings: () => set({ settingsOpen: true }),
  closeSettings: () => set({ settingsOpen: false }),

  fetchModelSettings: () => simpleFetch('/settings', ModelSettingsSchema, 'modelSettings', 'settingsLoading')(set),

  fetchAvailableModels: () => simpleFetch('/settings/models', z.array(RequestyModelSchema), 'availableModels', 'modelsLoading')(set),

  updateModelSettings: async (settings: Partial<ModelSettings>) => {
    try {
      const res = await apiFetch(`${BASE}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = validateResponse(ModelSettingsSchema, await res.json(), '/settings')
      set({ modelSettings: data })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchUserSettings: async () => {
    try {
      const res = await apiFetch(`${BASE}/settings/user`)
      if (!res.ok) return
      const data = validateResponse(UserSettingsSchema, await res.json(), '/settings/user')
      set({ userSettings: data })
      if (data.theme === 'light' || data.theme === 'dark' || data.theme === 'system') {
        applyTheme(data.theme)
      }
      if (data.chat_mode === 'normal' || data.chat_mode === 'planning') {
        set({ chatMode: data.chat_mode })
      }
      if (data.interaction_style === 'auto' || data.interaction_style === 'coach' || data.interaction_style === 'consultant') {
        set({ interactionStyle: data.interaction_style as InteractionStyle })
      }
    } catch {
      // ignore
    }
  },

  updateUserSettings: async (settings: Partial<UserSettings>) => {
    try {
      const res = await apiFetch(`${BASE}/settings/user`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = validateResponse(UserSettingsSchema, await res.json(), '/settings/user')
      set({ userSettings: data })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  // User profile
  userProfile: null,
  userProfileLoading: false,

  fetchUserProfile: async () => {
    set({ userProfileLoading: true })
    try {
      const res = await apiFetch(`${BASE}/things/me`)
      if (!res.ok) {
        set({ userProfile: null })
        return
      }
      const data = validateResponse(UserProfileSchema, await res.json(), '/things/me')
      set({ userProfile: data as UserProfile })
    } catch {
      set({ userProfile: null })
    } finally {
      set({ userProfileLoading: false })
    }
  },

  updateUserThing: async (updates: { title?: string; data?: Record<string, unknown> }) => {
    const profile = get().userProfile
    if (!profile) return
    try {
      const res = await apiFetch(`${BASE}/things/${profile.thing.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const updated: Thing = validateResponse(ThingSchema, await res.json(), `/things/${profile.thing.id}`)
      set({ userProfile: { ...profile, thing: updated } })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  // Merge suggestions
  mergeSuggestions: [],
  mergeSuggestionsLoading: false,
  mergeInProgress: false,

  fetchMergeSuggestions: () => simpleFetch('/things/merge-suggestions?limit=10', z.array(MergeSuggestionSchema), 'mergeSuggestions', 'mergeSuggestionsLoading')(set),

  executeMerge: async (keepId: string, removeId: string) => {
    set({ mergeInProgress: true })
    try {
      const res = await apiFetch(`${BASE}/things/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keep_id: keepId, remove_id: removeId }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      validateResponse(MergeResultSchema, await res.json(), '/things/merge')
      // Remove the suggestion from the list and refresh things
      set(state => ({
        mergeSuggestions: state.mergeSuggestions.filter(
          s => !(s.thing_a.id === keepId && s.thing_b.id === removeId) &&
               !(s.thing_a.id === removeId && s.thing_b.id === keepId)
        ),
      }))
      get().fetchThings()
      get().fetchMergeSuggestions()
    } catch (e) {
      set({ error: String(e) })
    } finally {
      set({ mergeInProgress: false })
    }
  },

  dismissMergeSuggestion: (thingAId: string, thingBId: string) => {
    set(state => ({
      mergeSuggestions: state.mergeSuggestions.filter(
        s => !(s.thing_a.id === thingAId && s.thing_b.id === thingBId)
      ),
    }))
  },

  // Connection suggestions
  connectionSuggestions: [],
  connectionSuggestionsLoading: false,
  connectionAcceptInProgress: false,

  fetchConnectionSuggestions: () => simpleFetch('/connections/suggestions?status=pending&limit=10', z.array(ConnectionSuggestionSchema), 'connectionSuggestions', 'connectionSuggestionsLoading')(set),

  acceptConnectionSuggestion: async (id: string, relationshipType?: string) => {
    set({ connectionAcceptInProgress: true })
    try {
      const body = relationshipType ? { relationship_type: relationshipType } : {}
      const res = await apiFetch(`${BASE}/connections/suggestions/${id}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      set(state => ({
        connectionSuggestions: state.connectionSuggestions.filter(s => s.id !== id),
      }))
      // Refresh things since a new relationship was created
      get().fetchThings()
    } catch (e) {
      set({ error: String(e) })
    } finally {
      set({ connectionAcceptInProgress: false })
    }
  },

  dismissConnectionSuggestion: async (id: string) => {
    try {
      const res = await apiFetch(`${BASE}/connections/suggestions/${id}/dismiss`, { method: 'POST' })
      if (!res.ok) return
      set(state => ({
        connectionSuggestions: state.connectionSuggestions.filter(s => s.id !== id),
      }))
    } catch {
      // ignore
    }
  },

  deferConnectionSuggestion: async (id: string) => {
    try {
      const res = await apiFetch(`${BASE}/connections/suggestions/${id}/defer`, { method: 'POST' })
      if (!res.ok) return
      set(state => ({
        connectionSuggestions: state.connectionSuggestions.filter(s => s.id !== id),
      }))
    } catch {
      // ignore
    }
  },

  // Preference toasts
  preferenceToasts: [],
  dismissPreferenceToast: (id: string) =>
    set(state => ({ preferenceToasts: state.preferenceToasts.filter(t => t.id !== id) })),

  // Preference feedback
  submitPreferenceFeedback: async (thingId: string, accurate: boolean) => {
    try {
      const res = await apiFetch(`${BASE}/preferences/${thingId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accurate }),
      })
      if (!res.ok) return
      get().fetchThings()
    } catch { /* best-effort */ }
  },

  // Command palette
  commandPaletteOpen: false,
  openCommandPalette: () => set({ commandPaletteOpen: true }),
  closeCommandPalette: () => set({ commandPaletteOpen: false }),

  // Quick-add dialog
  quickAddOpen: false,
  openQuickAdd: () => set({ quickAddOpen: true }),
  closeQuickAdd: () => set({ quickAddOpen: false }),

  // Sidebar visibility (desktop)
  sidebarOpen: typeof window !== 'undefined' ? window.innerWidth >= 768 : true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set(s => ({ sidebarOpen: !s.sidebarOpen })),

  // toggleRightView alias
  toggleRightView: () => set(s => ({ rightView: s.rightView === 'chat' ? 'briefing' : 'chat' })),

  // Feedback
  feedbackOpen: false,
  openFeedback: () => set({ feedbackOpen: true }),
  closeFeedback: () => set({ feedbackOpen: false }),

  // Create a Thing
  createThing: async (title: string, typeHint?: string, checkinDate?: string) => {
    const res = await apiFetch(`${BASE}/things`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, type_hint: typeHint ?? null, checkin_date: checkinDate ?? null }),
    })
    if (!res.ok) throw new Error(`Failed to create thing: ${res.status}`)
    const data = validateResponse(ThingSchema, await res.json(), '/things POST')
    // Refresh things list
    get().fetchThings()
    return data
  },

  // Chat input focus
  _chatInputFocusFn: null,
  registerChatInputFocus: (fn: () => void) => set({ _chatInputFocusFn: fn }),
  focusChatInput: () => {
    const fn = get()._chatInputFocusFn
    if (fn) fn()
  },
  submitFeedback: async (data) => {
    try {
      const res = await apiFetch(`${BASE}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        return { success: false, error: errData.detail || `HTTP ${res.status}` }
      }
      const result = await res.json()
      return { success: true, issueUrl: result.issue_url }
    } catch (e) {
      return { success: false, error: String(e) }
    }
  },
}))
