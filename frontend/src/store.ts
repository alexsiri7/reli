import { create } from 'zustand'
import { apiFetch } from './api'
import { setTheme as applyTheme } from './hooks/useTheme'
import { cacheThings, getCachedThings } from './offline/cache-things'
import { cacheThingTypes, getCachedThingTypes } from './offline/cache-thing-types'
import { cacheRelationships, getCachedRelationships } from './offline/cache-relationships'
import { cacheBriefing, getCachedBriefing } from './offline/cache-briefing'
import { cacheCalendarEvents, getCachedCalendarEvents } from './offline/cache-calendar'
import { getByKey } from './offline/idb'
import { mutationFetch } from './offline/mutation-fetch'
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
  ChatResponseSchema,
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

// ── Generated types (from Pydantic models via OpenAPI) ────────────────────────
// Re-exported so existing imports from './store' continue to work.
export type {
  ThingType,
  Thing,
  Relationship,
  CallUsage,
  ModelUsage,
  ProactiveSurface,
  FocusRecommendation,
  ConflictAlert,
  SweepFinding,
  LearnedPreference,
  MorningBriefingItem,
  MorningBriefingFinding,
  MorningBriefingContent,
  MorningBriefing,
  BriefingPreferences,
  Nudge,
  WeeklyBriefingItem,
  WeeklyBriefingConnection,
  WeeklyBriefingContent,
  WeeklyBriefing,
  ModelSettings,
  RequestyModel,
  UserSettings,
  UserProfileRelationship,
  UserProfile,
  MergeSuggestionThing,
  MergeSuggestion,
  ConnectionSuggestionThing,
  ConnectionSuggestion,
} from './generated/api-types'

import type {
  Thing,
  ThingType,
  CallUsage,
  ModelUsage,
  Relationship,
  RequestyModel,
  ProactiveSurface,
  FocusRecommendation,
  ConflictAlert,
  SweepFinding,
  LearnedPreference,
  MorningBriefing,
  BriefingPreferences,
  Nudge,
  WeeklyBriefing,
  ModelSettings,
  UserSettings,
  UserProfile,
  MergeSuggestion,
  ConnectionSuggestion,
} from './generated/api-types'

// ── Frontend-only types (not derived from Pydantic models) ────────────────────

export type TypeHint = 'task' | 'note' | 'project' | 'idea' | 'goal' | 'journal' | 'person' | 'place' | 'event' | 'concept' | 'reference' | 'preference' | string

export interface WebSearchResult {
  title: string
  url: string
  snippet: string
}

export interface ContextThing {
  id: string
  title: string
  type_hint?: string | null
}

export interface GmailMessage {
  id: string
  subject: string
  from: string
  date: string
  snippet: string
}

export interface ReferencedThing {
  mention: string
  thing_id: string
}

export interface AppliedChanges {
  created?: { id: string; title: string; type_hint?: string }[]
  updated?: { id: string; title: string; [key: string]: unknown }[]
  deleted?: string[]
  context_things?: ContextThing[]
  referenced_things?: ReferencedThing[]
  web_results?: WebSearchResult[]
  gmail_context?: GmailMessage[]
  calendar_events?: CalendarEvent[]
}

// BriefingItem.thing is dict[str, Any] in backend but always a Thing in practice
export interface BriefingItem {
  thing: Thing
  importance: number
  urgency: number
  score: number
  reasons: string[]
}

export interface BriefingStats {
  active_things: number
  checkin_due: number
  overdue: number
}

export interface CalendarEvent {
  id: string
  summary: string
  start: string
  end: string
  all_day: boolean
  location: string | null
  status: string
}

export interface CalendarStatus {
  configured: boolean
  connected: boolean
}

export interface GmailStatus {
  connected: boolean
  email: string | null
}

export type InteractionStyle = 'auto' | 'coach' | 'consultant'

export type ChatMode = 'normal' | 'planning'

export type StreamingStage = 'context' | 'reasoning' | 'response' | null

export interface SessionStats {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  api_calls: number
  cost_usd: number
  per_model: ModelUsage[]
}

export interface ChatMessage {
  id: number | string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  applied_changes: AppliedChanges | null
  questions_for_user: string[]
  prompt_tokens?: number
  completion_tokens?: number
  cost_usd?: number
  model?: string | null
  per_call_usage?: CallUsage[]
  timestamp: string
  streaming?: boolean
  streamingStage?: StreamingStage
}

export interface AuthUser {
  id: string
  email: string
  name: string
  picture: string | null
}

interface ReliState {
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
  fetchHistory: () => Promise<void>
  fetchOlderMessages: () => Promise<void>
  sendMessage: (text: string) => Promise<void>
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
  createThing: (title: string, typeHint?: string) => Promise<Thing>

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

const BASE = '/api'

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

function _preferenceConfidenceLabel(data: unknown): string {
  if (!data || typeof data !== 'object') return ''
  const d = data as Record<string, unknown>
  if (typeof d.confidence === 'number') {
    const c = d.confidence as number
    return c >= 0.7 ? 'strong' : c >= 0.5 ? 'moderate' : 'emerging'
  }
  if (Array.isArray(d.patterns) && d.patterns.length > 0) {
    const first = d.patterns[0] as Record<string, unknown>
    return String(first.confidence ?? 'emerging')
  }
  return ''
}

function _parsePreferenceToasts(
  changes: AppliedChanges | null | undefined
): { id: string; title: string; confidenceLabel: string; action: 'created' | 'updated' }[] {
  if (!changes) return []
  const toasts: { id: string; title: string; confidenceLabel: string; action: 'created' | 'updated' }[] = []
  const ts = Date.now()
  const checkItem = (item: Record<string, unknown>, action: 'created' | 'updated') => {
    if ((item.type_hint as string | undefined) !== 'preference') return
    let data = item.data
    if (typeof data === 'string') {
      try { data = JSON.parse(data) } catch { data = null }
    }
    toasts.push({
      id: `pref-toast-${ts}-${item.id}`,
      title: String(item.title ?? ''),
      confidenceLabel: _preferenceConfidenceLabel(data),
      action,
    })
  }
  for (const c of changes.created ?? []) checkItem(c as Record<string, unknown>, 'created')
  for (const u of changes.updated ?? []) checkItem(u as Record<string, unknown>, 'updated')
  return toasts
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
  briefingPreferences: null,

  nudges: [],
  nudgesLoading: false,
  weeklyBriefing: null,
  weeklyBriefingLoading: false,

  fetchMorningBriefing: async () => {
    set({ morningBriefingLoading: true })
    try {
      const res = await apiFetch(`${BASE}/briefing/morning`)
      if (!res.ok) return
      const data = validateResponse(MorningBriefingSchema, await res.json(), '/briefing/morning')
      set({ morningBriefing: data })
    } catch {
      // best-effort
    } finally {
      set({ morningBriefingLoading: false })
    }
  },

  fetchBriefingPreferences: async () => {
    try {
      const res = await apiFetch(`${BASE}/briefing/preferences`)
      if (!res.ok) return
      const data = validateResponse(BriefingPreferencesSchema, await res.json(), '/briefing/preferences')
      set({ briefingPreferences: data })
    } catch {
      // best-effort
    }
  },

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
      await apiFetch(`${BASE}/nudges/${nudgeId}/stop`, { method: 'POST' })
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
    fetchThingDetailWithFallback(id).then(([thing, rels]) => {
      if (get().detailThingId === id) {
        set({ detailThing: thing, detailRelationships: rels, detailLoading: false })
      }
    }).catch(() => {
      if (get().detailThingId === id) set({ detailLoading: false })
    })
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
    fetchThingDetailWithFallback(id).then(([thing, rels]) => {
      if (get().detailThingId === id) {
        set({ detailThing: thing, detailRelationships: rels, detailLoading: false })
      }
    }).catch(() => {
      if (get().detailThingId === id) set({ detailLoading: false })
    })
  },

  goBackThingDetail: () => {
    const history = get().detailHistory
    if (history.length === 0) return
    const prevId = history[history.length - 1]!
    set({ detailThingId: prevId, detailHistory: history.slice(0, -1), detailLoading: true, detailThing: null, detailRelationships: [] })
    fetchThingDetailWithFallback(prevId).then(([thing, rels]) => {
      if (get().detailThingId === prevId) {
        set({ detailThing: thing, detailRelationships: rels, detailLoading: false })
      }
    }).catch(() => {
      if (get().detailThingId === prevId) set({ detailLoading: false })
    })
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
      const things: Thing[] = []
      const theOneThing: BriefingItem | null = data.the_one_thing ?? null
      if (data.the_one_thing) things.push(data.the_one_thing.thing)
      const secondaryItems: BriefingItem[] = data.secondary ?? []
      for (const item of secondaryItems) things.push(item.thing)
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
      if (res.status === 202) {
        // Queued offline — optimistically remove from UI
        set(state => ({ findings: state.findings.filter(f => f.id !== findingId) }))
        return
      }
      if (!res.ok) return
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

  sendMessage: async (text: string) => {
    const userMsg: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: get().sessionId,
      role: 'user',
      content: text,
      applied_changes: null,
      questions_for_user: [],
      timestamp: new Date().toISOString(),
    }
    const placeholderMsg: ChatMessage = {
      id: `pending-${Date.now()}`,
      session_id: get().sessionId,
      role: 'assistant',
      content: '',
      applied_changes: null,
      questions_for_user: [],
      timestamp: new Date().toISOString(),
      streaming: true,
      streamingStage: 'context',
    }

    set(state => ({
      messages: [...state.messages, userMsg, placeholderMsg],
      chatLoading: true,
    }))

    try {
      const res = await apiFetch(`${BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: get().sessionId, message: text, mode: get().chatMode }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        // Keep the last potentially incomplete line in the buffer
        buffer = lines.pop() ?? ''

        let eventType = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ') && eventType) {
            const data = JSON.parse(line.slice(6))

            if (eventType === 'stage') {
              const stage = data.stage as 'context' | 'reasoning' | 'response'
              const status = data.status as 'started' | 'complete'
              if (status === 'started') {
                set(state => ({
                  messages: state.messages.map(m =>
                    m.streaming ? { ...m, streamingStage: stage } : m,
                  ),
                }))
              }
            } else if (eventType === 'token') {
              set(state => ({
                messages: state.messages.map(m =>
                  m.streaming ? { ...m, content: m.content + data.text } : m,
                ),
              }))
            } else if (eventType === 'complete') {
              const chatData = validateResponse(ChatResponseSchema, data, '/chat/stream')
              const assistantMsg: ChatMessage = {
                id: `assistant-${Date.now()}`,
                session_id: get().sessionId,
                role: 'assistant',
                content: chatData.reply,
                applied_changes: chatData.applied_changes ?? null,
                questions_for_user: chatData.questions_for_user ?? [],
                prompt_tokens: chatData.usage?.prompt_tokens ?? 0,
                completion_tokens: chatData.usage?.completion_tokens ?? 0,
                cost_usd: chatData.usage?.cost_usd ?? 0,
                model: chatData.usage?.model ?? null,
                per_call_usage: chatData.usage?.per_call_usage ?? [],
                timestamp: new Date().toISOString(),
              }
              const newToasts = _parsePreferenceToasts(chatData.applied_changes)
              const updates: Partial<ReliState> = {
                messages: get().messages.map(m => m.streaming ? assistantMsg : m),
              }
              if (chatData.session_usage) {
                updates.sessionStats = chatData.session_usage
              }
              if (newToasts.length > 0) {
                updates.preferenceToasts = [...get().preferenceToasts, ...newToasts]
              }
              set(updates as ReliState)
            } else if (eventType === 'error') {
              throw new Error(data.message || 'Pipeline error')
            }

            eventType = ''
          }
        }
      }

      // Refresh things in case the pipeline made changes
      get().fetchThings()
      get().fetchBriefing()
      get().fetchProactiveSurfaces()
      get().fetchFocusRecommendations()
      get().fetchConflictAlerts()
    } catch (e) {
      set(state => ({
        messages: state.messages.map(m =>
          m.streaming
            ? { ...m, content: m.content || 'Error communicating with server.', streaming: false, streamingStage: null }
            : m,
        ),
        error: String(e),
      }))
    } finally {
      set({ chatLoading: false })
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

  fetchModelSettings: async () => {
    set({ settingsLoading: true })
    try {
      const res = await apiFetch(`${BASE}/settings`)
      if (!res.ok) return
      const data = validateResponse(ModelSettingsSchema, await res.json(), '/settings')
      set({ modelSettings: data })
    } catch {
      // ignore
    } finally {
      set({ settingsLoading: false })
    }
  },

  fetchAvailableModels: async () => {
    set({ modelsLoading: true })
    try {
      const res = await apiFetch(`${BASE}/settings/models`)
      if (!res.ok) return
      const data = validateResponse(z.array(RequestyModelSchema), await res.json(), '/settings/models')
      set({ availableModels: data })
    } catch {
      // ignore
    } finally {
      set({ modelsLoading: false })
    }
  },

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

  fetchMergeSuggestions: async () => {
    set({ mergeSuggestionsLoading: true })
    try {
      const res = await apiFetch(`${BASE}/things/merge-suggestions?limit=10`)
      if (!res.ok) return
      const data: MergeSuggestion[] = validateResponse(z.array(MergeSuggestionSchema), await res.json(), '/things/merge-suggestions')
      set({ mergeSuggestions: data })
    } catch {
      // best-effort
    } finally {
      set({ mergeSuggestionsLoading: false })
    }
  },

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

  fetchConnectionSuggestions: async () => {
    set({ connectionSuggestionsLoading: true })
    try {
      const res = await apiFetch(`${BASE}/connections/suggestions?status=pending&limit=10`)
      if (!res.ok) return
      const data: ConnectionSuggestion[] = validateResponse(z.array(ConnectionSuggestionSchema), await res.json(), '/connections/suggestions')
      set({ connectionSuggestions: data })
    } catch {
      // best-effort
    } finally {
      set({ connectionSuggestionsLoading: false })
    }
  },

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
  createThing: async (title: string, typeHint?: string) => {
    const res = await apiFetch(`${BASE}/things`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, type_hint: typeHint ?? null }),
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
