import { apiFetch } from './api'
import { readChatStream } from './chat/stream-reader'
import { parsePreferenceToasts } from './format/preferences'
import { validateResponse, ChatResponseSchema } from './schemas'
import type { ChatMessage, StreamingStage } from './types'
import type { ReliState } from './store'
import { z } from 'zod'

const BASE = '/api'

export interface SendMessageDeps {
  set: (partial: Partial<ReliState> | ((state: ReliState) => Partial<ReliState>)) => void
  get: () => ReliState
}

export function buildOptimisticMessages(sessionId: string, text: string): [ChatMessage, ChatMessage] {
  const userMsg: ChatMessage = {
    id: `local-${Date.now()}`,
    session_id: sessionId,
    role: 'user',
    content: text,
    applied_changes: null,
    questions_for_user: [],
    timestamp: new Date().toISOString(),
  }
  const placeholderMsg: ChatMessage = {
    id: `pending-${Date.now()}`,
    session_id: sessionId,
    role: 'assistant',
    content: '',
    applied_changes: null,
    questions_for_user: [],
    timestamp: new Date().toISOString(),
    streaming: true,
    streamingStage: 'context',
  }
  return [userMsg, placeholderMsg]
}

export async function handleRateLimitResponse(
  res: Response,
  set: SendMessageDeps['set'],
): Promise<boolean> {
  if (res.status !== 429) return false
  const body = await res.json().catch((err) => {
    console.warn('[chat] Failed to parse 429 body, defaulting retry_after to 60', err)
    return {}
  })
  const retry_after = Number(body.retry_after) || 60
  const unit = retry_after === 1 ? 'second' : 'seconds'
  set((state: ReliState) => ({
    messages: state.messages.map((m: ChatMessage) =>
      m.streaming
        ? { ...m, content: `Too many requests — please wait ${retry_after} ${unit} before sending another message.`, streaming: false, streamingStage: null }
        : m,
    ),
  }))
  return true
}

export function buildAssistantMessage(
  chatData: z.infer<typeof ChatResponseSchema>,
  sessionId: string,
): ChatMessage {
  return {
    id: `assistant-${Date.now()}`,
    session_id: sessionId,
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
}

export async function executeSendMessage(text: string, { set, get }: SendMessageDeps): Promise<void> {
  const [userMsg, placeholderMsg] = buildOptimisticMessages(get().sessionId, text)

  set((state: ReliState) => ({
    messages: [...state.messages, userMsg, placeholderMsg],
    chatLoading: true,
  }))

  try {
    const res = await apiFetch(`${BASE}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: get().sessionId, message: text, mode: get().chatMode }),
    })

    if (await handleRateLimitResponse(res, set)) return
    if (!res.ok) throw new Error(`HTTP ${res.status}`)

    const reader = res.body?.getReader()
    if (!reader) throw new Error('No response body')

    await readChatStream(reader, {
      onStage: (stage: StreamingStage) => {
        set((state: ReliState) => ({
          messages: state.messages.map((m: ChatMessage) =>
            m.streaming ? { ...m, streamingStage: stage } : m,
          ),
        }))
      },
      onToken: (token: string) => {
        set((state: ReliState) => ({
          messages: state.messages.map((m: ChatMessage) =>
            m.streaming ? { ...m, content: m.content + token } : m,
          ),
        }))
      },
      onComplete: (data: unknown) => {
        const chatData = validateResponse(ChatResponseSchema, data, '/chat/stream')
        const assistantMsg = buildAssistantMessage(chatData, get().sessionId)
        const newToasts = parsePreferenceToasts(chatData.applied_changes)
        const updates: Partial<ReliState> = {
          messages: get().messages.map((m: ChatMessage) => m.streaming ? assistantMsg : m),
        }
        if (chatData.session_usage) {
          updates.sessionStats = chatData.session_usage
        }
        if (newToasts.length > 0) {
          updates.preferenceToasts = [...get().preferenceToasts, ...newToasts]
        }
        set(updates)
      },
      onError: (message: string) => {
        throw new Error(message)
      },
    })

    // Refresh things in case the pipeline made changes
    get().fetchThings()
    get().fetchBriefing()
    get().fetchProactiveSurfaces()
    get().fetchFocusRecommendations()
    get().fetchConflictAlerts()
    get().fetchChatSessions()
  } catch (e) {
    set((state: ReliState) => ({
      messages: state.messages.map((m: ChatMessage) =>
        m.streaming
          ? { ...m, content: m.content || 'Error communicating with server.', streaming: false, streamingStage: null }
          : m,
      ),
      error: String(e),
    }))
  } finally {
    set({ chatLoading: false })
  }
}
