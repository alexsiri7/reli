// ── Shared frontend types ────────────────────────────────────────────────────
// Types used across components, offline modules, and the store.
// Extracted from store.ts so consumers don't depend on the Zustand store module.

import type {
  Thing,
  ThingType,
  CallUsage,
  ModelUsage,
  Nudge,
} from './generated/api-types'

export type { Thing, ThingType, ModelUsage, Nudge }

export type { TypeHint } from './utils'

export interface ChatSession {
  id: string
  title: string
  origin: string | null
  created_at: string
  last_active_at: string
  message_count: number
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
  role: 'user' | 'assistant' | 'system'
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
