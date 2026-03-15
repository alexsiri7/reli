import { create } from 'zustand'

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
  children_count: number | null
  completed_count: number | null
}

export interface WebSearchResult {
  title: string
  url: string
  snippet: string
}

export interface AppliedChanges {
  created?: { id: string; title: string; type_hint?: string }[]
  updated?: { id: string; title: string; [key: string]: unknown }[]
  deleted?: string[]
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

export interface ModelUsage {
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  api_calls: number
}

export interface SessionStats {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  api_calls: number
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

interface ReliState {
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
  fetchThingTypes: () => Promise<void>
  fetchThings: () => Promise<void>
  fetchBriefing: () => Promise<void>
  fetchProactiveSurfaces: () => Promise<void>
  dismissFinding: (findingId: string) => Promise<void>
  snoozeThing: (id: string, checkinDate: string | null) => Promise<void>
  fetchHistory: () => Promise<void>
  fetchOlderMessages: () => Promise<void>
  sendMessage: (text: string) => Promise<void>
  clearError: () => void
  fetchCalendarStatus: () => Promise<void>
  fetchCalendarEvents: () => Promise<void>
  connectCalendar: () => Promise<void>
  disconnectCalendar: () => Promise<void>
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

export const useStore = create<ReliState>((set, get) => ({
  thingTypes: [],
  things: [],
  briefing: [],
  findings: [],
  messages: [],
  sessionId: SESSION_ID,
  sessionStats: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, api_calls: 0, per_model: [] },
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

  searchThings: async (query: string) => {
    if (!query.trim()) {
      set({ searchResults: [], searchLoading: false })
      return
    }
    set({ searchLoading: true })
    try {
      const res = await fetch(`${BASE}/things/search?q=${encodeURIComponent(query)}&limit=50`)
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
      const res = await fetch(`${BASE}/thing-types`)
      if (!res.ok) return
      const data: ThingType[] = await res.json()
      set({ thingTypes: data })
    } catch {
      // best-effort
    }
  },

  fetchThings: async () => {
    set({ loading: true, error: null })
    try {
      const res = await fetch(`${BASE}/things?active_only=true&limit=200`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: Thing[] = await res.json()
      set({ things: data })
    } catch (e) {
      set({ error: String(e) })
    } finally {
      set({ loading: false })
    }
  },

  fetchBriefing: async () => {
    try {
      const res = await fetch(`${BASE}/briefing`)
      if (!res.ok) return
      const data = await res.json()
      set({ briefing: data.things ?? [], findings: data.findings ?? [] })
    } catch {
      // ignore — briefing is best-effort
    }
  },

  fetchProactiveSurfaces: async () => {
    try {
      const res = await fetch(`${BASE}/proactive?days=7`)
      if (!res.ok) return
      const data: ProactiveSurface[] = await res.json()
      set({ proactiveSurfaces: data })
    } catch {
      // best-effort
    }
  },

  dismissFinding: async (findingId: string) => {
    try {
      const res = await fetch(`${BASE}/briefing/findings/${findingId}/dismiss`, { method: 'PATCH' })
      if (!res.ok) return
      set(state => ({ findings: state.findings.filter(f => f.id !== findingId) }))
    } catch {
      // ignore
    }
  },

  snoozeThing: async (id: string, checkinDate: string | null) => {
    try {
      const res = await fetch(`${BASE}/things/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkin_date: checkinDate }),
      })
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

  fetchHistory: async () => {
    set({ historyLoading: true })
    try {
      const res = await fetch(`${BASE}/chat/history/${SESSION_ID}?limit=${HISTORY_PAGE_SIZE}`)
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
      const res = await fetch(
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
      const res = await fetch(`${BASE}/chat`, {
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
      const res = await fetch(`${BASE}/calendar/status`)
      if (!res.ok) return
      const data: CalendarStatus = await res.json()
      set({ calendarStatus: data })
    } catch {
      // ignore
    }
  },

  fetchCalendarEvents: async () => {
    try {
      const res = await fetch(`${BASE}/calendar/events`)
      if (!res.ok) return
      const data = await res.json()
      set({ calendarEvents: data.events ?? [] })
    } catch {
      // ignore
    }
  },

  connectCalendar: async () => {
    try {
      const res = await fetch(`${BASE}/calendar/auth`)
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
      const res = await fetch(`${BASE}/calendar/disconnect`, { method: 'DELETE' })
      if (!res.ok) return
      set({ calendarStatus: { configured: true, connected: false }, calendarEvents: [] })
    } catch (e) {
      set({ error: String(e) })
    }
  },

  clearError: () => set({ error: null }),
}))
