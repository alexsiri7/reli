import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type AppliedChanges, type CalendarEvent, type ChatMessage, type ChatMode, type ContextThing, type GmailMessage, type InteractionStyle, type ModelUsage, type ReferencedThing, type SessionStats, type StreamingStage, type WebSearchResult } from '../store'
import { typeIcon } from '../utils'
import { useVoiceInput, speechRecognitionSupported } from '../hooks/useVoiceInput'
import { useTTS, ttsSupported } from '../hooks/useTTS'
import { useNetworkStatus } from '../hooks/useNetworkStatus'

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
              <span className="block text-gray-400 dark:text-gray-400 truncate">{r.snippet}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function GmailSources({ messages }: { messages: GmailMessage[] }) {
  const [expanded, setExpanded] = useState(false)

  if (messages.length === 0) return null

  return (
    <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 transition-colors"
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
        {messages.length} email{messages.length !== 1 ? 's' : ''}
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-1.5">
          {messages.map((m, i) => (
            <div
              key={i}
              className="text-xs text-gray-600 dark:text-gray-300"
            >
              <span className="font-medium">{m.subject}</span>
              <span className="text-gray-400 dark:text-gray-400"> — {m.from}</span>
              <span className="block text-gray-400 dark:text-gray-400 truncate">{m.snippet}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CalendarSources({ events }: { events: CalendarEvent[] }) {
  const [expanded, setExpanded] = useState(false)

  if (events.length === 0) return null

  return (
    <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 transition-colors"
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
        {events.length} event{events.length !== 1 ? 's' : ''}
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-1.5">
          {events.map((ev, i) => (
            <div
              key={i}
              className="text-xs text-gray-600 dark:text-gray-300"
            >
              <span className="font-medium">{ev.summary}</span>
              <span className="text-gray-400 dark:text-gray-400"> — {new Date(ev.start).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>
              {ev.location && (
                <span className="block text-gray-400 dark:text-gray-400 truncate">{ev.location}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ContextDropdown({ changes }: { changes: AppliedChanges }) {
  const [expanded, setExpanded] = useState(false)
  const thingTypes = useStore(s => s.thingTypes)
  const openThingDetail = useStore(s => s.openThingDetail)

  const contextThings = changes.context_things ?? []
  const created = changes.created ?? []
  const updated = changes.updated ?? []
  const deleted = changes.deleted ?? []
  const hasEffects = created.length > 0 || updated.length > 0 || deleted.length > 0
  const hasContext = contextThings.length > 0

  if (!hasContext && !hasEffects) return null

  const totalCount = contextThings.length + created.length + updated.length + deleted.length

  return (
    <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors cursor-pointer"
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
        Context &amp; changes
        <span className="text-gray-400 dark:text-gray-400 font-normal">({totalCount})</span>
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-2">
          {/* Context section — Things that informed the response */}
          {hasContext ? (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-400 font-semibold mb-1">Context</p>
              <div className="space-y-0.5">
                {contextThings.map((t: ContextThing) => (
                  <button
                    key={t.id}
                    onClick={() => openThingDetail(t.id)}
                    className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors w-full text-left cursor-pointer"
                  >
                    <span>{typeIcon(t.type_hint, thingTypes)}</span>
                    <span className="truncate">{t.title}</span>
                    {t.type_hint && (
                      <span className="text-[10px] text-gray-400 dark:text-gray-400 capitalize ml-auto shrink-0">{t.type_hint}</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-[10px] text-gray-400 dark:text-gray-400 italic">No database context used</p>
          )}

          {/* Effects section — Things that were created/updated/deleted */}
          {hasEffects && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-400 font-semibold mb-1">Effects</p>
              <div className="space-y-0.5">
                {created.map(c => (
                  <button
                    key={c.id}
                    onClick={() => openThingDetail(c.id)}
                    className="flex items-center gap-1.5 text-xs w-full text-left hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors cursor-pointer"
                  >
                    <span className="font-medium text-green-600 dark:text-green-400 shrink-0">Created</span>
                    <span>{typeIcon(c.type_hint, thingTypes)}</span>
                    <span className="truncate text-gray-600 dark:text-gray-300">{c.title}</span>
                  </button>
                ))}
                {updated.map(u => (
                  <button
                    key={u.id}
                    onClick={() => openThingDetail(u.id)}
                    className="flex items-center gap-1.5 text-xs w-full text-left hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors cursor-pointer"
                  >
                    <span className="font-medium text-amber-600 dark:text-amber-400 shrink-0">Updated</span>
                    <span>{typeIcon((u as { type_hint?: string }).type_hint, thingTypes)}</span>
                    <span className="truncate text-gray-600 dark:text-gray-300">{u.title}</span>
                  </button>
                ))}
                {deleted.map(id => (
                  <div
                    key={id}
                    className="flex items-center gap-1.5 text-xs"
                  >
                    <span className="font-medium text-red-500 dark:text-red-400 shrink-0">Deleted</span>
                    <span className="truncate text-gray-600 dark:text-gray-300">{id}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function UsagePill({ msg }: { msg: ChatMessage }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const totalTokens = (msg.prompt_tokens ?? 0) + (msg.completion_tokens ?? 0)
  const calls = msg.per_call_usage ?? []

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (totalTokens === 0) return null

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="text-[10px] text-gray-400 dark:text-gray-400 font-mono hover:text-gray-600 dark:hover:text-gray-300 transition-colors cursor-pointer"
      >
        {formatTokens(totalTokens)} tokens{msg.cost_usd != null && msg.cost_usd > 0 ? ` · ${formatCost(msg.cost_usd)}` : ''}
      </button>
      {open && (
        <div className="absolute left-0 bottom-full mb-1 z-50 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-2.5 min-w-[200px] font-mono text-[11px] text-gray-500 dark:text-gray-400">
          {calls.length > 1 ? (
            <>
              <p className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-gray-400 mb-1">Per-call breakdown</p>
              <div className="space-y-2">
                {calls.map((call, i) => (
                  <div key={i}>
                    <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 truncate">
                      {call.model.split('/').pop()}
                    </p>
                    <div className="space-y-0.5 mt-0.5">
                      <div className="flex justify-between gap-3">
                        <span>Prompt</span>
                        <span className="tabular-nums">{formatTokens(call.prompt_tokens)}</span>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span>Completion</span>
                        <span className="tabular-nums">{formatTokens(call.completion_tokens)}</span>
                      </div>
                      {call.cost_usd > 0 && (
                        <div className="flex justify-between gap-3 text-gray-600 dark:text-gray-300">
                          <span>Cost</span>
                          <span className="tabular-nums">{formatCost(call.cost_usd)}</span>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <div className="border-t border-gray-200 dark:border-gray-700 pt-1.5 mt-1.5 font-medium text-gray-700 dark:text-gray-300">
                <div className="flex justify-between">
                  <span>Total</span>
                  <span className="tabular-nums">{formatTokens(totalTokens)}</span>
                </div>
                {msg.cost_usd != null && msg.cost_usd > 0 && (
                  <div className="flex justify-between mt-0.5">
                    <span>Cost</span>
                    <span className="tabular-nums">{formatCost(msg.cost_usd)}</span>
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              {msg.model && (
                <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1.5 truncate">
                  {msg.model.split('/').pop()}
                </p>
              )}
              <div className="space-y-0.5">
                <div className="flex justify-between">
                  <span>Prompt</span>
                  <span className="tabular-nums">{formatTokens(msg.prompt_tokens ?? 0)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Completion</span>
                  <span className="tabular-nums">{formatTokens(msg.completion_tokens ?? 0)}</span>
                </div>
                <div className="flex justify-between border-t border-gray-200 dark:border-gray-700 pt-0.5 mt-0.5 font-medium text-gray-700 dark:text-gray-300">
                  <span>Total</span>
                  <span className="tabular-nums">{formatTokens(totalTokens)}</span>
                </div>
              </div>
              {msg.cost_usd != null && msg.cost_usd > 0 && (
                <p className="mt-1.5 text-right text-gray-600 dark:text-gray-300 font-medium">
                  {formatCost(msg.cost_usd)}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function SpeakButton({ msg, speakingId, speak }: { msg: ChatMessage; speakingId: string | null; speak: (text: string, id: string) => void }) {
  if (!ttsSupported || msg.role === 'user') return null

  const isSpeaking = speakingId === String(msg.id)

  return (
    <button
      onClick={() => speak(msg.content, String(msg.id))}
      className={`p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${
        isSpeaking ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400 dark:text-gray-400'
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

const STAGE_LABELS: Record<string, string> = {
  context: 'Searching memory\u2026',
  reasoning: 'Thinking\u2026',
  response: 'Writing response\u2026',
}

function StreamingIndicator({ stage }: { stage: StreamingStage }) {
  if (!stage) return null
  const label = STAGE_LABELS[stage] ?? stage

  return (
    <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-400 py-1">
      <span className="flex gap-0.5">
        {['context', 'reasoning', 'response'].map(s => (
          <span
            key={s}
            className={`w-1.5 h-1.5 rounded-full transition-colors duration-300 ${
              s === stage
                ? 'bg-indigo-500 animate-pulse'
                : ['context', 'reasoning', 'response'].indexOf(s) < ['context', 'reasoning', 'response'].indexOf(stage)
                  ? 'bg-indigo-400'
                  : 'bg-gray-300 dark:bg-gray-600'
            }`}
          />
        ))}
      </span>
      <span>{label}</span>
    </div>
  )
}

/**
 * Replace referenced Thing mentions in content with markdown links using a
 * `thing://` scheme so they can be intercepted by a custom ReactMarkdown
 * link component. Matches are case-insensitive and longest-first to avoid
 * partial replacements.
 */
function injectThingLinks(content: string, refs: ReferencedThing[]): string {
  if (refs.length === 0) return content
  // Sort longest mention first to avoid partial matches
  const sorted = [...refs].sort((a, b) => b.mention.length - a.mention.length)
  let result = content
  for (const ref of sorted) {
    // Escape special regex chars in the mention
    const escaped = ref.mention.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    // Replace all occurrences, case-insensitive, but only if not already inside a markdown link
    const re = new RegExp(`(?<!\\[)${escaped}(?!\\]\\()`, 'gi')
    result = result.replace(re, `[${ref.mention}](thing://${ref.thing_id})`)
  }
  return result
}

function MessageBubble({ msg, speakingId, speak }: { msg: ChatMessage; speakingId: string | null; speak: (text: string, id: string) => void }) {
  const isUser = msg.role === 'user'
  const ts = formatTimestamp(msg.timestamp)
  const openThingDetail = useStore(s => s.openThingDetail)

  const referencedThings = msg.applied_changes?.referenced_things ?? []
  const renderedContent = referencedThings.length > 0
    ? injectThingLinks(msg.content, referencedThings)
    : msg.content

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
          {msg.streaming && !msg.content && msg.streamingStage ? (
            <StreamingIndicator stage={msg.streamingStage} />
          ) : isUser ? (
            <>
              {msg.content}
              {msg.streaming && msg.content && (
                <span className="inline-block w-1.5 h-4 bg-current opacity-75 ml-0.5 animate-pulse align-middle" />
              )}
            </>
          ) : (
            <>
              <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-pre:my-2 prose-blockquote:my-1">
                <ReactMarkdown
                  urlTransform={(url) => url}
                  components={{
                    a: ({ href, children }) => {
                      if (href?.startsWith('thing://')) {
                        const thingId = href.replace('thing://', '')
                        return (
                          <button
                            onClick={() => openThingDetail(thingId)}
                            className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 underline decoration-indigo-300 dark:decoration-indigo-500 underline-offset-2 cursor-pointer font-medium"
                          >
                            {children}
                          </button>
                        )
                      }
                      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                    },
                  }}
                >
                  {renderedContent}
                </ReactMarkdown>
              </div>
              {msg.streaming && msg.content && (
                <span className="inline-block w-1.5 h-4 bg-current opacity-75 ml-0.5 animate-pulse align-middle" />
              )}
            </>
          )}
          {!isUser && msg.applied_changes?.web_results && msg.applied_changes.web_results.length > 0 && (
            <WebSources results={msg.applied_changes.web_results} />
          )}
          {!isUser && msg.applied_changes?.gmail_context && msg.applied_changes.gmail_context.length > 0 && (
            <GmailSources messages={msg.applied_changes.gmail_context} />
          )}
          {!isUser && msg.applied_changes?.calendar_events && msg.applied_changes.calendar_events.length > 0 && (
            <CalendarSources events={msg.applied_changes.calendar_events} />
          )}
          {!isUser && msg.applied_changes && (
            <ContextDropdown changes={msg.applied_changes} />
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
            <span className="text-[10px] text-gray-400 dark:text-gray-400">
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
        title="Today's usage stats"
        aria-label="Today's usage stats"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 13h2v8H3zM9 8h2v13H9zM15 11h2v10h-2zM21 4h2v17h-2z" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3 min-w-[280px] font-mono text-[11px] text-gray-500 dark:text-gray-400">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-xs text-gray-700 dark:text-gray-300">Today's Usage</span>
            <span className="text-gray-400">{formatTokens(stats.total_tokens)} tokens · {stats.api_calls} call{stats.api_calls !== 1 ? 's' : ''} · {formatCost(stats.cost_usd)}</span>
          </div>
          {stats.per_model.length > 0 ? (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-gray-400 dark:text-gray-400">
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
            <p className="text-center text-gray-400 dark:text-gray-400 py-2">No usage yet</p>
          )}
        </div>
      )}
    </div>
  )
}

function ModeToggle({ mode, onChange }: { mode: ChatMode; onChange: (mode: ChatMode) => void }) {
  const isPlanning = mode === 'planning'

  return (
    <button
      onClick={() => onChange(isPlanning ? 'normal' : 'planning')}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
        isPlanning
          ? 'bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 ring-1 ring-violet-300 dark:ring-violet-600'
          : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
      }`}
      title={isPlanning ? 'Switch to Normal mode' : 'Switch to Planning mode'}
      aria-label={`Current mode: ${mode}. Click to switch.`}
    >
      {isPlanning ? (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498 4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 0 0-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0Z" />
        </svg>
      ) : (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
        </svg>
      )}
      {isPlanning ? 'Planning' : 'Normal'}
    </button>
  )
}

function InteractionStyleSelector({ style, onChange }: { style: InteractionStyle; onChange: (style: InteractionStyle) => void }) {
  const styles: { value: InteractionStyle; label: string; icon: React.ReactNode; title: string }[] = [
    {
      value: 'auto',
      label: 'Auto',
      title: 'Dynamically adapt between coaching and consulting based on context',
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
        </svg>
      ),
    },
    {
      value: 'coach',
      label: 'Coach',
      title: 'Guide discovery through questions and reflection',
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
        </svg>
      ),
    },
    {
      value: 'consultant',
      label: 'Consultant',
      title: 'Provide direct answers and recommendations',
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z" />
        </svg>
      ),
    },
  ]

  return (
    <div className="flex items-center rounded-lg bg-gray-100 dark:bg-gray-800 p-0.5" role="radiogroup" aria-label="Interaction style">
      {styles.map(s => (
        <button
          key={s.value}
          onClick={() => onChange(s.value)}
          className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-all ${
            style === s.value
              ? s.value === 'coach'
                ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 shadow-sm'
                : s.value === 'consultant'
                ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 shadow-sm'
                : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 shadow-sm'
              : 'text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300'
          }`}
          title={s.title}
          aria-label={`${s.label} style: ${s.title}`}
          role="radio"
          aria-checked={style === s.value}
        >
          {s.icon}
          <span className="hidden sm:inline">{s.label}</span>
        </button>
      ))}
    </div>
  )
}

export function ChatPanel() {
  const { messages, chatLoading, historyLoading, hasMoreHistory, sendMessage, fetchOlderMessages, sessionStats, chatMode, setChatMode, interactionStyle, setInteractionStyle } = useStore(
    useShallow(s => ({
      messages: s.messages,
      chatLoading: s.chatLoading,
      historyLoading: s.historyLoading,
      hasMoreHistory: s.hasMoreHistory,
      sendMessage: s.sendMessage,
      fetchOlderMessages: s.fetchOlderMessages,
      sessionStats: s.sessionStats,
      chatMode: s.chatMode,
      setChatMode: s.setChatMode,
      interactionStyle: s.interactionStyle,
      setInteractionStyle: s.setInteractionStyle,
    }))
  )
  const { isOnline } = useNetworkStatus()
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

  // Scroll to bottom instantly on initial mount
  const hasMountScrolled = useRef(false)
  useEffect(() => {
    if (!hasMountScrolled.current && messages.length > 0) {
      hasMountScrolled.current = true
      bottomRef.current?.scrollIntoView()
    }
  }, [messages])

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
    } else if (hasMountScrolled.current) {
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
    <div className="flex-1 flex flex-col bg-gray-50 dark:bg-gray-900 min-w-0 min-h-0 mobile-chat-pb md:pb-0">
      {/* Title bar */}
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shrink-0 flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div>
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Chat</h2>
            <p className="text-xs text-gray-400 dark:text-gray-400">Talk to Reli — create, update, and query your Things</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <InteractionStyleSelector style={interactionStyle} onChange={setInteractionStyle} />
          <ModeToggle mode={chatMode} onChange={setChatMode} />
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
            <p className="text-sm text-gray-400 dark:text-gray-400 mt-1 max-w-xs">
              Try: "Remind me to check the server logs tomorrow" or "I had an idea about the new API design"
            </p>
          </div>
        )}
        {messages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} speakingId={speakingId} speak={speak} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 pb-4 pt-2 bg-white dark:bg-gray-950 border-t border-gray-200 dark:border-gray-800 shrink-0">
        {!isOnline && (
          <div className="mb-2 px-3 py-2 text-sm text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 rounded-xl text-center">
            Chat requires an internet connection
          </div>
        )}
        <div className="flex items-end gap-2 bg-gray-100 dark:bg-gray-800 rounded-2xl px-3 py-2">
          <textarea
            ref={inputRef}
            rows={1}
            maxLength={10000}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={isOnline ? "Message Reli\u2026" : "Chat unavailable offline"}
            disabled={!isOnline}
            className="flex-1 bg-transparent resize-none outline-none text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-400 max-h-32 py-1 leading-relaxed disabled:opacity-50 disabled:cursor-not-allowed"
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
                  : 'text-gray-400 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
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
            disabled={!input.trim() || chatLoading || !isOnline}
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
        <p className="text-xs text-gray-400 dark:text-gray-400 text-center mt-1.5">
          Enter to send · Shift+Enter for new line{speechRecognitionSupported ? ' · 🎤 for voice' : ''}
        </p>
      </div>
    </div>
  )
}
