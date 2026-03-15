import { useCallback, useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type AppliedChanges, type ChatMessage, type ModelUsage, type SessionStats, type WebSearchResult } from '../store'
import { useVoiceInput, speechRecognitionSupported } from '../hooks/useVoiceInput'
import { useTTS, ttsSupported, useAvailableVoices, getStoredVoiceURI, setStoredVoiceURI } from '../hooks/useTTS'

function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (isNaN(date.getTime())) return ''
  const now = new Date()
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  const time = date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  if (isToday) return time
  const monthDay = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  return `${monthDay}, ${time}`
}

function WebSources({ results }: { results: WebSearchResult[] }) {
  const [expanded, setExpanded] = useState(false)

  if (results.length === 0) return null

  return (
    <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 transition-colors"
      >
        <svg
          className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        {results.length} source{results.length !== 1 ? 's' : ''}
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-1.5">
          {results.map((r, i) => (
            <a
              key={i}
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-xs text-gray-600 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
            >
              <span className="font-medium">{r.title}</span>
              <span className="block text-gray-400 dark:text-gray-500 truncate">{r.snippet}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function ActionEntry({ changes }: { changes: AppliedChanges }) {
  const items: { label: string; detail: string }[] = []

  if (changes.created) {
    for (const c of changes.created) {
      const hint = c.type_hint ? ` (${c.type_hint})` : ''
      items.push({ label: 'Created', detail: `${c.title}${hint}` })
    }
  }
  if (changes.updated) {
    for (const u of changes.updated) {
      items.push({ label: 'Updated', detail: u.title })
    }
  }
  if (changes.deleted) {
    for (const id of changes.deleted) {
      items.push({ label: 'Deleted', detail: id })
    }
  }

  if (items.length === 0) return null

  return (
    <div className="flex flex-col items-center gap-1 my-2">
      {items.map((item, i) => (
        <div
          key={i}
          className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400"
        >
          <span
            className={`font-medium ${
              item.label === 'Created'
                ? 'text-green-600 dark:text-green-400'
                : item.label === 'Updated'
                  ? 'text-amber-600 dark:text-amber-400'
                  : 'text-red-500 dark:text-red-400'
            }`}
          >
            {item.label}:
          </span>
          <span>{item.detail}</span>
        </div>
      ))}
    </div>
  )
}

function UsagePill({ msg }: { msg: ChatMessage }) {
  const totalTokens = (msg.prompt_tokens ?? 0) + (msg.completion_tokens ?? 0)
  if (totalTokens === 0) return null

  return (
    <span className="text-[10px] text-gray-400 dark:text-gray-500 font-mono">
      {formatTokens(totalTokens)} tokens
    </span>
  )
}

function SpeakButton({ msg, speakingId, speak }: { msg: ChatMessage; speakingId: string | null; speak: (text: string, id: string) => void }) {
  if (!ttsSupported || msg.role === 'user') return null

  const isSpeaking = speakingId === String(msg.id)

  return (
    <button
      onClick={() => speak(msg.content, String(msg.id))}
      className={`p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${
        isSpeaking ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400 dark:text-gray-500'
      }`}
      title={isSpeaking ? 'Stop speaking' : 'Read aloud'}
      aria-label={isSpeaking ? 'Stop speaking' : 'Read aloud'}
    >
      {isSpeaking ? (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 6h12v12H6z" />
        </svg>
      ) : (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 0 1 0 12.728M16.463 8.288a5.25 5.25 0 0 1 0 7.424M6.75 8.25l4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25h2.24z" />
        </svg>
      )}
    </button>
  )
}

function VoiceSettings() {
  const [open, setOpen] = useState(false)
  const voices = useAvailableVoices()
  const [selectedURI, setSelectedURI] = useState(getStoredVoiceURI)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (!ttsSupported || voices.length <= 1) return null

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
        title="Voice settings"
        aria-label="Voice settings"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 0 1 0 12.728M16.463 8.288a5.25 5.25 0 0 1 0 7.424M6.75 8.25l4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25h2.24z" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3 min-w-[220px]">
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">TTS Voice</label>
          <select
            value={selectedURI ?? ''}
            onChange={e => {
              const uri = e.target.value || null
              setSelectedURI(uri)
              setStoredVoiceURI(uri)
            }}
            className="w-full text-xs rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 px-2 py-1.5"
          >
            <option value="">Default</option>
            {voices.map(v => (
              <option key={v.voiceURI} value={v.voiceURI}>
                {v.name} ({v.lang})
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}

function MessageBubble({ msg, speakingId, speak }: { msg: ChatMessage; speakingId: string | null; speak: (text: string, id: string) => void }) {
  const isUser = msg.role === 'user'
  const ts = formatTimestamp(msg.timestamp)

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-indigo-600 text-white text-xs flex items-center justify-center shrink-0 mr-2 mt-1 font-bold">
          R
        </div>
      )}
      <div className="flex flex-col max-w-[75%]">
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
            isUser
              ? 'bg-indigo-600 text-white rounded-br-sm'
              : 'bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 border border-gray-200 dark:border-gray-700 rounded-bl-sm'
          }`}
        >
          {msg.content}
          {msg.streaming && (
            <span className="inline-block w-1.5 h-4 bg-current opacity-75 ml-0.5 animate-pulse align-middle" />
          )}
          {!isUser && msg.applied_changes?.web_results && msg.applied_changes.web_results.length > 0 && (
            <WebSources results={msg.applied_changes.web_results} />
          )}
          {!isUser && msg.questions_for_user && msg.questions_for_user.length > 0 && (
            <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600">
              {msg.questions_for_user.map((q, i) => (
                <p key={i} className="text-sm font-medium text-indigo-600 dark:text-indigo-300">
                  {q}
                </p>
              ))}
            </div>
          )}
        </div>
        <div className={`flex items-center gap-2 mt-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
          {ts && (
            <span className="text-[10px] text-gray-400 dark:text-gray-500">
              {ts}
            </span>
          )}
          {!isUser && <UsagePill msg={msg} />}
          {!isUser && <SpeakButton msg={msg} speakingId={speakingId} speak={speak} />}
        </div>
      </div>
    </div>
  )
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function formatCost(usd: number): string {
  if (usd === 0) return '$0.00'
  if (usd < 0.01) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function ModelRow({ m }: { m: ModelUsage }) {
  return (
    <tr className="border-t border-gray-200 dark:border-gray-700">
      <td className="py-1.5 pr-3 text-gray-700 dark:text-gray-300 font-medium whitespace-nowrap">
        {m.model.split('/').pop()}
      </td>
      <td className="py-1.5 px-3 text-right tabular-nums">{formatTokens(m.prompt_tokens)}</td>
      <td className="py-1.5 px-3 text-right tabular-nums">{formatTokens(m.completion_tokens)}</td>
      <td className="py-1.5 px-3 text-right tabular-nums">{m.api_calls}</td>
      <td className="py-1.5 pl-3 text-right tabular-nums">{formatCost(m.cost_usd)}</td>
    </tr>
  )
}

function NerdStatsIcon({ stats }: { stats: SessionStats }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
        title="Session usage stats"
        aria-label="Session usage stats"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 13h2v8H3zM9 8h2v13H9zM15 11h2v10h-2zM21 4h2v17h-2z" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3 min-w-[280px] font-mono text-[11px] text-gray-500 dark:text-gray-400">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-xs text-gray-700 dark:text-gray-300">Session Usage</span>
            <span className="text-gray-400">{formatTokens(stats.total_tokens)} tokens · {stats.api_calls} call{stats.api_calls !== 1 ? 's' : ''} · {formatCost(stats.cost_usd)}</span>
          </div>
          {stats.per_model.length > 0 ? (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-gray-400 dark:text-gray-500">
                  <th className="text-left font-normal pr-3 pb-1">Model</th>
                  <th className="text-right font-normal px-3 pb-1">Prompt</th>
                  <th className="text-right font-normal px-3 pb-1">Compl.</th>
                  <th className="text-right font-normal px-3 pb-1">Calls</th>
                  <th className="text-right font-normal pl-3 pb-1">Cost</th>
                </tr>
              </thead>
              <tbody>
                {stats.per_model.map(m => (
                  <ModelRow key={m.model} m={m} />
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-center text-gray-400 dark:text-gray-500 py-2">No usage yet</p>
          )}
        </div>
      )}
    </div>
  )
}

export function ChatPanel() {
  const { messages, chatLoading, historyLoading, hasMoreHistory, sendMessage, fetchOlderMessages, sessionStats } = useStore(
    useShallow(s => ({
      messages: s.messages,
      chatLoading: s.chatLoading,
      historyLoading: s.historyLoading,
      hasMoreHistory: s.hasMoreHistory,
      sendMessage: s.sendMessage,
      fetchOlderMessages: s.fetchOlderMessages,
      sessionStats: s.sessionStats,
    }))
  )
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const { speakingId, speak } = useTTS()

  const handleTranscript = useCallback((text: string) => {
    setInput(prev => (prev ? prev + ' ' + text : text))
    inputRef.current?.focus()
  }, [])
  const { listening, toggleListening } = useVoiceInput(handleTranscript)
  const prevScrollHeightRef = useRef<number>(0)
  const isLoadingOlderRef = useRef(false)

  // Auto-scroll to bottom on new messages (but not when loading older ones)
  useEffect(() => {
    if (isLoadingOlderRef.current) {
      // Preserve scroll position after prepending older messages
      const container = scrollContainerRef.current
      if (container) {
        const newScrollHeight = container.scrollHeight
        container.scrollTop = newScrollHeight - prevScrollHeightRef.current
      }
      isLoadingOlderRef.current = false
    } else {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current
    if (!container || historyLoading || !hasMoreHistory) return

    if (container.scrollTop < 100) {
      isLoadingOlderRef.current = true
      prevScrollHeightRef.current = container.scrollHeight
      fetchOlderMessages()
    }
  }, [historyLoading, hasMoreHistory, fetchOlderMessages])

  const submit = async () => {
    const text = input.trim()
    if (!text || chatLoading) return
    setInput('')
    await sendMessage(text)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-gray-50 dark:bg-gray-900 min-w-0">
      {/* Title bar */}
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shrink-0 flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Chat</h2>
          <p className="text-xs text-gray-400 dark:text-gray-500">Talk to Reli — create, update, and query your Things</p>
        </div>
        <div className="flex items-center gap-1">
          <VoiceSettings />
          <NerdStatsIcon stats={sessionStats} />
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto px-5 py-4"
        onScroll={handleScroll}
      >
        {historyLoading && hasMoreHistory && (
          <div className="flex justify-center py-2">
            <span className="w-4 h-4 border-2 border-gray-300 border-t-indigo-600 rounded-full animate-spin" />
          </div>
        )}
        {messages.length === 0 && !historyLoading && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="text-5xl mb-4">✨</div>
            <h3 className="text-base font-semibold text-gray-700 dark:text-gray-200">What's on your mind?</h3>
            <p className="text-sm text-gray-400 dark:text-gray-500 mt-1 max-w-xs">
              Try: "Remind me to check the server logs tomorrow" or "I had an idea about the new API design"
            </p>
          </div>
        )}
        {messages.map(msg => (
          <div key={msg.id}>
            {msg.role === 'assistant' && msg.applied_changes && (
              <ActionEntry changes={msg.applied_changes} />
            )}
            <MessageBubble msg={msg} speakingId={speakingId} speak={speak} />
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 pb-4 pt-2 bg-white dark:bg-gray-950 border-t border-gray-200 dark:border-gray-800 shrink-0">
        <div className="flex items-end gap-2 bg-gray-100 dark:bg-gray-800 rounded-2xl px-3 py-2">
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Message Reli…"
            className="flex-1 bg-transparent resize-none outline-none text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 max-h-32 py-1 leading-relaxed"
            style={{ height: 'auto' }}
            onInput={e => {
              const t = e.currentTarget
              t.style.height = 'auto'
              t.style.height = `${t.scrollHeight}px`
            }}
          />
          {speechRecognitionSupported && (
            <button
              onClick={toggleListening}
              className={`shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-colors ${
                listening
                  ? 'bg-red-500 text-white animate-pulse'
                  : 'text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
              title={listening ? 'Stop recording' : 'Voice input'}
              aria-label={listening ? 'Stop recording' : 'Voice input'}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z" />
              </svg>
            </button>
          )}
          <button
            onClick={submit}
            disabled={!input.trim() || chatLoading}
            className="shrink-0 w-8 h-8 rounded-xl bg-indigo-600 text-white flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:bg-indigo-700 transition-colors"
            title="Send (Enter)"
          >
            {chatLoading ? (
              <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-600 text-center mt-1.5">
          Enter to send · Shift+Enter for new line{speechRecognitionSupported ? ' · 🎤 for voice' : ''}
        </p>
      </div>
    </div>
  )
}
