import { create } from 'zustand'
import { apiFetch } from './api'
import { cacheThings, getCachedThings } from './offline/cache-things'
import { cacheThingTypes, getCachedThingTypes } from './offline/cache-thing-types'
import { cacheRelationships, getCachedRelationships } from './offline/cache-relationships'
import { cacheBriefing, getCachedBriefing } from './offline/cache-briefing'
import { cacheCalendarEvents, getCachedCalendarEvents } from './offline/cache-calendar'
import { getByKey } from './offline/idb'
import { mutationFetch } from './offline/mutation-fetch'

export type TypeHint = 'task' | 'note' | 'project' | 'idea' | 'goal' | 'journal' | 'person' | 'place' | 'event' | 'concept' | 'reference' | string

export interface ThingType {
  id: string
  name: string
  icon: string
  color: string | null
  created_at: string
}

export interface Thing {
  id: string
  title: string
  type_hint: TypeHint | null
  parent_id: string | null
  checkin_date: string | null
  priority: number
  active: boolean
  surface: boolean
  data: Record<string, unknown> | null
  created_at: string
  updated_at: string
  last_referenced: string | null
  open_questions: string[] | null
  children_count: number | null
  completed_count: number | null
}

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

export interface AppliedChanges {
  created?: { id: string; title: string; type_hint?: string }[]
  updated?: { id: string; title: string; [key: string]: unknown }[]
  deleted?: string[]
  context_things?: ContextThing[]
  web_results?: WebSearchResult[]
}

export interface ProactiveSurface {
  thing: Thing
  reason: string
  date_key: string
  days_away: number
}

export interface SweepFinding {
  id: string
  thing_id: string | null
  finding_type: string
  message: string
  priority: number
  dismissed: boolean
  created_at: string
  expires_at: string | null
  snoozed_until: string | null
  thing: Thing | null
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

export interface ModelSettings {
  context: string
  reasoning: string
  response: string
  chat_context_window: number
}

export interface RequestyModel {
  id: string
  name: string | null
}

export interface ModelUsage {
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  api_calls: number
  cost_usd: number
}

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
  timestamp: string
  streaming?: boolean
}

export interface Relationship {
  id: string
  from_thing_id: string
  to_thing_id: string
  relationship_type: string
  metadata: Record<string, unknown> | null
  created_at: string
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
  findings: SweepFinding[]
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

  proactiveSurfaces: ProactiveSurface[]
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
  dismissFinding: (findingId: string) => Promise<void>
  snoozeFinding: (findingId: string, until: string) => Promise<void>
  actOnFinding: (finding: SweepFinding) => void
  snoozeThing: (id: string, checkinDate: string | null) => Promise<void>
  fetchHistory: () => Promise<void>
  fetchOlderMessages: () => Promise<void>
  sendMessage: (text: string) => Promise<void>
  clearError: () => void
  fetchCalendarStatus: () => Promise<void>
  fetchCalendarEvents: () => Promise<void>
  connectCalendar: () => Promise<void>
  disconnectCalendar: () => Promise<void>

  // Things list filter (client-side, persists across panel switches)
  thingFilterQuery: string
  thingFilterTypes: string[]
  setThingFilterQuery: (query: string) => void
  toggleThingFilterType: (type: string) => void
  clearThingFilters: () => void

  // Mobile navigation
  mobileView: 'things' | 'chat'
  setMobileView: (view: 'things' | 'chat') => void

  // Settings
  settingsOpen: boolean
  modelSettings: ModelSettings | null
  availableModels: RequestyModel[]
  settingsLoading: boolean
  modelsLoading: boolean
  openSettings: () => void
  closeSettings: () => void
  fetchModelSettings: () => Promise<void>
  fetchAvailableModels: () => Promise<void>
  updateModelSettings: (settings: Partial<ModelSettings>) => Promise<void>
}

const HISTORY_PAGE_SIZE = 20

function getOrCreateSessionId(): string {
  const key = 'reli-session-id'
  const stored = localStorage.getItem(key)
  if (stored) return stored
  const id = `reli-${Math.random().toString(36).slice(2)}`
  localStorage.setItem(key, id)
  return id
}

const SESSION_ID = getOrCreateSessionId()

const BASE = '/api'

async function fetchThingDetailWithFallback(
  id: string,
): Promise<[Thing | null, Relationship[]]> {
  try {
    const [thing, rels] = await Promise.all([
      apiFetch(`${BASE}/things/${id}`).then(r => r.ok ? r.json() : null),
      apiFetch(`${BASE}/things/${id}/relationships`).then(r => r.ok ? r.json() : []),
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

export const useStore = create<ReliState>((set, get) => ({
  currentUser: null,
  authChecked: false,

  fetchCurrentUser: async () => {
    try {
      const res = await apiFetch(`${BASE}/auth/me`)
      if (res.ok) {
        const user: AuthUser = await res.json()
        set({ currentUser: user, authChecked: true })
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
  findings: [],
  messages: [],
  sessionId: SESSION_ID,
  sessionStats: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, api_calls: 0, cost_usd: 0, per_model: [] },
  loading: false,
  chatLoading: false,
  historyLoading: false,
  hasMoreHistory: true,
  error: null,
  calendarStatus: { configured: false, connected: false },
  calendarEvents: [],
  proactiveSurfaces: [],
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
      const data: Thing[] = await res.json()
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
      const data: ThingType[] = await res.json()
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
      const data: Thing[] = await res.json()
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
      const data = await res.json()
      const things = data.things ?? []
      const findings = data.findings ?? []
      set({ briefing: things, findings })
      cacheBriefing(things, findings).catch(() => {})
    } catch {
      if (!navigator.onLine) {
        const cached = await getCachedBriefing().catch(() => undefined)
        if (cached) set({ briefing: cached.things, findings: cached.findings })
      }
    }
  },

  fetchProactiveSurfaces: async () => {
    try {
      const res = await apiFetch(`${BASE}/proactive?days=7`)
      if (!res.ok) return
      const data: ProactiveSurface[] = await res.json()
      set({ proactiveSurfaces: data })
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
      const updated: Thing = await res.json()
      set(state => ({
        things: state.things.map(t => t.id === id ? updated : t),
        briefing: state.briefing.map(t => t.id === id ? updated : t),
      }))
    } catch (e) {
      set({ error: String(e) })
    }
  },

  fetchDailyStats: async () => {
    try {
      const res = await apiFetch(`${BASE}/chat/stats/today`)
      if (!res.ok) return
      const data: SessionStats = await res.json()
      set({ sessionStats: data })
    } catch {
      // best-effort
    }
  },

  fetchHistory: async () => {
    set({ historyLoading: true })
    try {
      const res = await apiFetch(`${BASE}/chat/history/${SESSION_ID}?limit=${HISTORY_PAGE_SIZE}`)
      if (!res.ok) return
      const data: ChatMessage[] = await res.json()
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
      const res = await apiFetch(
        `${BASE}/chat/history/${SESSION_ID}?limit=${HISTORY_PAGE_SIZE}&before=${oldestMsg.id}`
      )
      if (!res.ok) return
      const data: ChatMessage[] = await res.json()
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
      session_id: SESSION_ID,
      role: 'user',
      content: text,
      applied_changes: null,
      questions_for_user: [],
      timestamp: new Date().toISOString(),
    }
    const placeholderMsg: ChatMessage = {
      id: `pending-${Date.now()}`,
      session_id: SESSION_ID,
      role: 'assistant',
      content: '',
      applied_changes: null,
      questions_for_user: [],
      timestamp: new Date().toISOString(),
      streaming: true,
    }

    set(state => ({
      messages: [...state.messages, userMsg, placeholderMsg],
      chatLoading: true,
    }))

    try {
      const res = await apiFetch(`${BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID, message: text }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        session_id: SESSION_ID,
        role: 'assistant',
        content: data.reply,
        applied_changes: data.applied_changes ?? null,
        questions_for_user: data.questions_for_user ?? [],
        prompt_tokens: data.usage?.prompt_tokens ?? 0,
        completion_tokens: data.usage?.completion_tokens ?? 0,
        cost_usd: data.usage?.cost_usd ?? 0,
        model: data.usage?.model ?? null,
        timestamp: new Date().toISOString(),
      }

      const updates: Partial<ReliState> = {
        messages: get().messages.map(m => m.streaming ? assistantMsg : m),
      }
      if (data.session_usage) {
        updates.sessionStats = data.session_usage
      }
      set(updates as ReliState)

      // Refresh things in case the pipeline made changes
      get().fetchThings()
      get().fetchBriefing()
      get().fetchProactiveSurfaces()
    } catch (e) {
      set(state => ({
        messages: state.messages.map(m =>
          m.streaming
            ? { ...m, content: 'Error communicating with server.', streaming: false }
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
      const data: CalendarStatus = await res.json()
      set({ calendarStatus: data })
    } catch {
      // ignore
    }
  },

  fetchCalendarEvents: async () => {
    try {
      const res = await apiFetch(`${BASE}/calendar/events`)
      if (!res.ok) return
      const data = await res.json()
      const events = data.events ?? []
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

  // Mobile navigation
  mobileView: 'things',
  setMobileView: (view) => set({ mobileView: view }),

  // Settings
  settingsOpen: false,
  modelSettings: null,
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
      const data = await res.json()
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
      const data = await res.json()
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
      const data = await res.json()
      set({ modelSettings: data })
    } catch (e) {
      set({ error: String(e) })
    }
  },
}))
