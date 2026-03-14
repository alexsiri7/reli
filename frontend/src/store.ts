import { create } from 'zustand'

export type TypeHint = 'task' | 'note' | 'project' | 'idea' | 'goal' | 'journal' | string

export interface Thing {
  id: string
  title: string
  type_hint: TypeHint | null
  parent_id: string | null
  checkin_date: string | null
  priority: number
  active: boolean
  data: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: number | string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  applied_changes: Record<string, unknown> | null
  timestamp: string
  streaming?: boolean
}

interface ReliState {
  things: Thing[]
  briefing: Thing[]
  messages: ChatMessage[]
  sessionId: string
  loading: boolean
  chatLoading: boolean
  error: string | null

  fetchThings: () => Promise<void>
  fetchBriefing: () => Promise<void>
  snoozeThing: (id: string, checkinDate: string | null) => Promise<void>
  fetchHistory: () => Promise<void>
  sendMessage: (text: string) => Promise<void>
  clearError: () => void
}

const SESSION_ID = `reli-${Math.random().toString(36).slice(2)}`

const BASE = '/api'

export const useStore = create<ReliState>((set, get) => ({
  things: [],
  briefing: [],
  messages: [],
  sessionId: SESSION_ID,
  loading: false,
  chatLoading: false,
  error: null,

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
      const data: Thing[] = await res.json()
      set({ briefing: data })
    } catch {
      // ignore — briefing is best-effort
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
    try {
      const res = await fetch(`${BASE}/chat/history/${SESSION_ID}?limit=100`)
      if (!res.ok) return
      const data: ChatMessage[] = await res.json()
      set({ messages: data })
    } catch {
      // ignore
    }
  },

  sendMessage: async (text: string) => {
    const userMsg: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: SESSION_ID,
      role: 'user',
      content: text,
      applied_changes: null,
      timestamp: new Date().toISOString(),
    }
    const placeholderMsg: ChatMessage = {
      id: `stream-${Date.now()}`,
      session_id: SESSION_ID,
      role: 'assistant',
      content: '',
      applied_changes: null,
      timestamp: new Date().toISOString(),
      streaming: true,
    }

    set(state => ({
      messages: [...state.messages, userMsg, placeholderMsg],
      chatLoading: true,
    }))

    try {
      // Persist user message
      await fetch(`${BASE}/chat/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: SESSION_ID,
          role: 'user',
          content: text,
        }),
      })

      // Simple echo response (full AI pipeline is Phase 5+)
      // For now, stream a placeholder assistant response
      const assistantText = `Got it! I've noted: "${text}". (AI pipeline coming in a future phase.)`

      // Simulate streaming
      let accumulated = ''
      for (const char of assistantText) {
        accumulated += char
        set(state => ({
          messages: state.messages.map(m =>
            m.streaming ? { ...m, content: accumulated } : m,
          ),
        }))
        await new Promise(r => setTimeout(r, 15))
      }

      // Persist assistant message
      const saveRes = await fetch(`${BASE}/chat/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: SESSION_ID,
          role: 'assistant',
          content: accumulated,
        }),
      })
      const saved: ChatMessage = await saveRes.json()

      set(state => ({
        messages: state.messages.map(m =>
          m.streaming ? { ...saved, streaming: false } : m,
        ),
      }))

      // Refresh things in case they changed
      get().fetchThings()
      get().fetchBriefing()
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

  clearError: () => set({ error: null }),
}))
