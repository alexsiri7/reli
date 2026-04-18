import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type AppliedChanges, type CalendarEvent, type ChatMessage, type ChatMode, type ContextThing, type GmailMessage, type InteractionStyle, type ModelUsage, type ReferencedThing, type SessionStats, type StreamingStage, type WebSearchResult } from '../store'
import { typeIcon } from '../utils'
import { useVoiceInput, speechRecognitionSupported } from '../hooks/useVoiceInput'
import { useTTS, ttsSupported } from '../hooks/useTTS'
import { useNetworkStatus } from '../hooks/useNetworkStatus'
import { useProgressiveDisclosure } from '../hooks/useProgressiveDisclosure'
import { NudgeBanner } from './NudgeBanner'

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

/** Format timestamp as "RELI / 10:42 AM" label */
function formatReliTimestamp(iso: string, isUser: boolean): string {
  const ts = formatTimestamp(iso)
  if (!ts) return ''
  return isUser ? ts : `RELI / ${ts}`
}

function ExpandChevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  )
}

function WebSources({ results }: { results: WebSearchResult[] }) {
  const [expanded, setExpanded] = useState(false)

  if (results.length === 0) return null

  return (
    <div className="mt-2 pt-2 border-t border-on-surface-variant/10">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
      >
        <ExpandChevron expanded={expanded} />
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
              className="block text-xs text-on-surface-variant hover:text-primary transition-colors"
            >
              <span className="font-medium">{r.title}</span>
              <span className="block text-on-surface-variant/60 truncate">{r.snippet}</span>
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
    <div className="mt-2 pt-2 border-t border-on-surface-variant/10">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-ideas hover:text-ideas/80 transition-colors"
      >
        <ExpandChevron expanded={expanded} />
        {messages.length} email{messages.length !== 1 ? 's' : ''}
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-1.5">
          {messages.map((m, i) => (
            <div
              key={i}
              className="text-xs text-on-surface-variant"
            >
              <span className="font-medium">{m.subject}</span>
              <span className="text-on-surface-variant/60"> — {m.from}</span>
              <span className="block text-on-surface-variant/60 truncate">{m.snippet}</span>
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
    <div className="mt-2 pt-2 border-t border-on-surface-variant/10">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-events hover:text-events/80 transition-colors"
      >
        <ExpandChevron expanded={expanded} />
        {events.length} event{events.length !== 1 ? 's' : ''}
      </button>
      {expanded && (
        <div className="mt-1.5 space-y-1.5">
          {events.map((ev, i) => (
            <div
              key={i}
              className="text-xs text-on-surface-variant"
            >
              <span className="font-medium">{ev.summary}</span>
              <span className="text-on-surface-variant/60"> — {new Date(ev.start).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>
              {ev.location && (
                <span className="block text-on-surface-variant/60 truncate">{ev.location}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Action Applied card — green SUCCESS badge with created/updated Things */
function ActionAppliedCard({ changes }: { changes: AppliedChanges }) {
  const thingTypes = useStore(s => s.thingTypes)
  const openThingDetail = useStore(s => s.openThingDetail)

  const contextThings = changes.context_things ?? []
  const created = changes.created ?? []
  const updated = changes.updated ?? []
  const deleted = changes.deleted ?? []
  const hasEffects = created.length > 0 || updated.length > 0 || deleted.length > 0
  const hasInferredConnections = contextThings.length > 0

  if (!hasInferredConnections && !hasEffects) return null

  return (
    <div className="mt-3 rounded-xl border border-projects/20 bg-projects/5 p-3 space-y-2">
      {/* SUCCESS badge */}
      {hasEffects && (
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-widest bg-projects/20 text-projects">
            SUCCESS
          </span>
        </div>
      )}

      {/* Created/Updated/Deleted items */}
      {hasEffects && (
        <div className="space-y-1">
          {created.map(c => (
            <button
              key={c.id}
              onClick={() => openThingDetail(c.id)}
              className="flex items-center gap-2 text-xs w-full text-left hover:text-primary transition-colors cursor-pointer group"
            >
              <span className="text-projects font-medium shrink-0">Created</span>
              <span>{typeIcon(c.type_hint, thingTypes)}</span>
              <span className="truncate text-on-surface group-hover:text-primary">{c.title}</span>
              <svg className="w-3 h-3 text-on-surface-variant/40 group-hover:text-primary ml-auto shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
            </button>
          ))}
          {updated.map(u => (
            <button
              key={u.id}
              onClick={() => openThingDetail(u.id)}
              className="flex items-center gap-2 text-xs w-full text-left hover:text-primary transition-colors cursor-pointer group"
            >
              <span className="text-events font-medium shrink-0">Updated</span>
              <span>{typeIcon((u as { type_hint?: string }).type_hint, thingTypes)}</span>
              <span className="truncate text-on-surface group-hover:text-primary">{u.title}</span>
              <svg className="w-3 h-3 text-on-surface-variant/40 group-hover:text-primary ml-auto shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
            </button>
          ))}
          {deleted.map(id => (
            <div
              key={id}
              className="flex items-center gap-2 text-xs"
            >
              <span className="font-medium text-ideas shrink-0">Deleted</span>
              <span className="truncate text-on-surface-variant">{id}</span>
            </div>
          ))}
        </div>
      )}

      {/* Inferred connections */}
      {hasInferredConnections && (
        <div>
          <p className="text-label text-on-surface-variant mb-1">Inferred connections</p>
          <div className="space-y-0.5">
            {contextThings.map((t: ContextThing) => (
              <button
                key={t.id}
                onClick={() => openThingDetail(t.id)}
                className="flex items-center gap-1.5 text-xs text-on-surface-variant hover:text-primary transition-colors w-full text-left cursor-pointer"
              >
                <span>{typeIcon(t.type_hint, thingTypes)}</span>
                <span className="truncate">{t.title}</span>
                {t.type_hint && (
                  <span className="text-[10px] text-on-surface-variant/60 capitalize ml-auto shrink-0">{t.type_hint}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/** Context chips — bottom bar showing context Things as pills */
function ContextChips({ changes }: { changes: AppliedChanges }) {
  const thingTypes = useStore(s => s.thingTypes)
  const openThingDetail = useStore(s => s.openThingDetail)
  const contextThings = changes.context_things ?? []
  const created = changes.created ?? []
  const updated = changes.updated ?? []

  const allThings = [
    ...created.map(c => ({ ...c, kind: 'created' as const })),
    ...updated.map(u => ({ ...u, kind: 'updated' as const })),
    ...contextThings.map(t => ({ ...t, kind: 'context' as const })),
  ]

  if (allThings.length === 0) return null

  return (
    <div className="flex items-center gap-1.5 flex-wrap mt-2">
      {allThings.map(t => (
        <button
          key={t.id}
          onClick={() => openThingDetail(t.id)}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-surface-container-high text-on-surface-variant hover:bg-surface-container-high/80 hover:text-on-surface transition-colors cursor-pointer"
        >
          <span className="text-xs">{typeIcon('type_hint' in t ? t.type_hint : undefined, thingTypes)}</span>
          <span className="truncate max-w-[120px]">{t.title}</span>
        </button>
      ))}
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
        className="text-[10px] text-on-surface-variant/60 font-mono hover:text-on-surface-variant transition-colors cursor-pointer"
      >
        {formatTokens(totalTokens)} tokens{msg.cost_usd != null && msg.cost_usd > 0 ? ` · ${formatCost(msg.cost_usd)}` : ''}
      </button>
      {open && (
        <div className="absolute left-0 bottom-full mb-1 z-50 glass rounded-lg shadow-lg p-2.5 min-w-[200px] font-mono text-[11px] text-on-surface-variant">
          {calls.length > 1 ? (
            <>
              <p className="text-label text-on-surface-variant/60 mb-1">Per-call breakdown</p>
              <div className="space-y-2">
                {calls.map((call, i) => (
                  <div key={i}>
                    <p className="text-xs font-semibold text-on-surface truncate">
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
                        <div className="flex justify-between gap-3 text-on-surface">
                          <span>Cost</span>
                          <span className="tabular-nums">{formatCost(call.cost_usd)}</span>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <div className="border-t border-on-surface-variant/10 pt-1.5 mt-1.5 font-medium text-on-surface">
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
                <p className="text-xs font-semibold text-on-surface mb-1.5 truncate">
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
                <div className="flex justify-between border-t border-on-surface-variant/10 pt-0.5 mt-0.5 font-medium text-on-surface">
                  <span>Total</span>
                  <span className="tabular-nums">{formatTokens(totalTokens)}</span>
                </div>
              </div>
              {msg.cost_usd != null && msg.cost_usd > 0 && (
                <p className="mt-1.5 text-right text-on-surface font-medium">
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
      className={`p-0.5 rounded hover:bg-surface-container-high transition-colors ${
        isSpeaking ? 'text-primary' : 'text-on-surface-variant/60'
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

const STAGES = ['context', 'reasoning', 'response']

function StreamingIndicator({ stage }: { stage: StreamingStage }) {
  if (!stage) return null
  const label = STAGE_LABELS[stage] ?? stage
  const currentIdx = STAGES.indexOf(stage)

  return (
    <div className="flex items-center gap-2 text-xs text-on-surface-variant py-1">
      <span className="flex gap-0.5">
        {STAGES.map((s, idx) => (
          <span
            key={s}
            className={`w-1.5 h-1.5 rounded-full transition-colors duration-300 ${
              s === stage
                ? 'bg-primary animate-pulse'
                : idx < currentIdx
                  ? 'bg-primary/60'
                  : 'bg-on-surface-variant/30'
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
  const ts = formatReliTimestamp(msg.timestamp, isUser)
  const openThingDetail = useStore(s => s.openThingDetail)

  const referencedThings = msg.applied_changes?.referenced_things ?? []
  const renderedContent = referencedThings.length > 0
    ? injectThingLinks(msg.content, referencedThings)
    : msg.content

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full gradient-cta text-white text-xs flex items-center justify-center shrink-0 mr-2.5 mt-1 font-bold">
          R
        </div>
      )}
      <div className={`flex flex-col ${isUser ? 'max-w-[75%] items-end' : 'max-w-[80%]'}`}>
        {/* Timestamp label */}
        {ts && (
          <span className={`text-label text-on-surface-variant/60 tracking-widest mb-1 ${isUser ? 'text-right' : ''}`}>
            {ts}
          </span>
        )}

        <div
          className={`text-sm leading-relaxed ${
            isUser
              ? 'bg-surface-container-high text-on-surface rounded-xl rounded-br-sm px-4 py-2.5'
              : 'border-l-4 border-primary pl-4 py-1'
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
              <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-pre:my-2 prose-blockquote:my-1 prose-pre:bg-surface-container-low prose-pre:border prose-pre:border-on-surface-variant/10 prose-code:text-primary">
                <ReactMarkdown
                  urlTransform={(url) => /^(javascript|data|vbscript):/i.test(url.trim()) ? '' : url}
                  components={{
                    a: ({ href, children }) => {
                      if (href?.startsWith('thing://')) {
                        const thingId = href.replace('thing://', '')
                        return (
                          <button
                            onClick={() => openThingDetail(thingId)}
                            className="text-primary hover:text-primary/80 underline decoration-primary/30 underline-offset-2 cursor-pointer font-medium"
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
          {!isUser && msg.questions_for_user && msg.questions_for_user.length > 0 && (
            <div className="mt-2 pt-2 border-t border-on-surface-variant/10">
              {msg.questions_for_user.map((q, i) => (
                <p key={i} className="text-sm font-medium text-primary">
                  {q}
                </p>
              ))}
            </div>
          )}
        </div>

        {/* Action Applied card */}
        {!isUser && msg.applied_changes && (
          <ActionAppliedCard changes={msg.applied_changes} />
        )}

        {/* Context chips */}
        {!isUser && msg.applied_changes && (
          <ContextChips changes={msg.applied_changes} />
        )}

        {/* Reli Suggestion card — for proactive suggestions */}
        {!isUser && msg.questions_for_user && msg.questions_for_user.length > 0 && (
          <div className="mt-2 rounded-xl border border-primary/20 bg-primary/5 p-3">
            <p className="text-label text-primary tracking-widest mb-1.5">SUGGESTION</p>
            {msg.questions_for_user.map((q, i) => (
              <p key={i} className="text-body text-on-surface mb-2">{q}</p>
            ))}
            <button className="gradient-cta px-4 py-1.5 rounded-lg text-xs font-semibold tracking-wider uppercase">
              Prepare Now
            </button>
          </div>
        )}

        {/* Usage + speak row */}
        <div className={`flex items-center gap-2 mt-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
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
    <tr className="border-t border-on-surface-variant/10">
      <td className="py-1.5 pr-3 text-on-surface font-medium whitespace-nowrap">
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
        className="p-1 rounded hover:bg-surface-container-high text-on-surface-variant transition-colors"
        title="Today's usage stats"
        aria-label="Today's usage stats"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 13h2v8H3zM9 8h2v13H9zM15 11h2v10h-2zM21 4h2v17h-2z" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 glass rounded-lg shadow-lg p-3 min-w-[280px] font-mono text-[11px] text-on-surface-variant">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-xs text-on-surface">Today's Usage</span>
            <span className="text-on-surface-variant/60">{formatTokens(stats.total_tokens)} tokens · {stats.api_calls} call{stats.api_calls !== 1 ? 's' : ''} · {formatCost(stats.cost_usd)}</span>
          </div>
          {stats.per_model.length > 0 ? (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-on-surface-variant/60">
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
            <p className="text-center text-on-surface-variant/60 py-2">No usage yet</p>
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
          ? 'bg-primary/15 text-primary ring-1 ring-primary/30'
          : 'bg-surface-container-high text-on-surface-variant hover:bg-surface-container-high/80 hover:text-on-surface'
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
    <div className="flex items-center rounded-lg bg-surface-container-high p-0.5" role="radiogroup" aria-label="Interaction style">
      {styles.map(s => (
        <button
          key={s.value}
          onClick={() => onChange(s.value)}
          className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-all ${
            style === s.value
              ? s.value === 'coach'
                ? 'bg-events/15 text-events shadow-sm'
                : s.value === 'consultant'
                ? 'bg-people/15 text-people shadow-sm'
                : 'bg-surface-container-low text-on-surface shadow-sm'
              : 'text-on-surface-variant hover:text-on-surface'
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
  const { messages, chatLoading, historyLoading, hasMoreHistory, sendMessage, fetchOlderMessages, sessionStats, chatMode, setChatMode, interactionStyle, setInteractionStyle, seedFromGoogle, googleSeedLoading, calendarStatus, gmailStatus, nudges, chatPrefill, clearChatPrefill } = useStore(
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
      seedFromGoogle: s.seedFromGoogle,
      googleSeedLoading: s.googleSeedLoading,
      calendarStatus: s.calendarStatus,
      gmailStatus: s.gmailStatus,
      nudges: s.nudges,
      chatPrefill: s.chatPrefill,
      clearChatPrefill: s.clearChatPrefill,
    }))
  )
  const { isOnline } = useNetworkStatus()
  const disclosure = useProgressiveDisclosure()
  const [input, setInput] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const { speakingId, speak } = useTTS()

  const handleTranscript = useCallback((text: string) => {
    setInput(prev => (prev ? prev + ' ' + text : text))
    inputRef.current?.focus()
  }, [])
  const { listening, toggleListening } = useVoiceInput(handleTranscript)
  const openThingDetailStore = useStore(s => s.openThingDetail)
  const thingTypes = useStore(s => s.thingTypes)

  // Collect unique context things from recent messages for mobile pills
  const activeContextThings = useMemo(() => {
    const seen = new Map<string, { id: string; title: string; type_hint?: string | null }>()
    for (let i = messages.length - 1; i >= 0 && seen.size < 8; i--) {
      const msg = messages[i]
      if (!msg) continue
      const changes = msg.applied_changes
      if (!changes) continue
      for (const t of changes.context_things ?? []) {
        if (!seen.has(t.id)) seen.set(t.id, { id: t.id, title: t.title, type_hint: t.type_hint })
      }
      for (const t of changes.referenced_things ?? []) {
        if (t.thing_id && !seen.has(t.thing_id)) seen.set(t.thing_id, { id: t.thing_id, title: t.mention, type_hint: undefined })
      }
    }
    return Array.from(seen.values())
  }, [messages])

  const prevScrollHeightRef = useRef<number>(0)
  const isLoadingOlderRef = useRef(false)

  // Register focus function for keyboard shortcut (/)
  const registerChatInputFocus = useStore(s => s.registerChatInputFocus)
  useEffect(() => {
    registerChatInputFocus(() => inputRef.current?.focus())
  }, [registerChatInputFocus])

  // Consume chatPrefill from store (e.g. briefing "Chat" action)
  useEffect(() => {
    if (!chatPrefill) return
    const prefill = chatPrefill
    clearChatPrefill()
    queueMicrotask(() => {
      setInput(prefill)
      inputRef.current?.focus()
    })
  }, [chatPrefill, clearChatPrefill])

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
    <div className="flex-1 flex flex-col bg-surface min-w-0 min-h-0 mobile-chat-pb md:pb-0">
      {/* Mobile header — compact with Reli branding */}
      <div className="md:hidden px-5 pt-4 pb-2 bg-surface shrink-0 flex items-center gap-2">
        <div className="w-7 h-7 rounded bg-primary-container flex items-center justify-center">
          <img src="/logo.svg" alt="Reli" className="h-4 w-4" />
        </div>
        <span className="text-lg font-bold text-on-surface tracking-tight">Reli</span>
      </div>

      {/* Desktop header — "Reli Assistant" with expand/collapse */}
      <div className="hidden md:flex px-5 py-3 border-b border-on-surface-variant/10 bg-surface-container-low shrink-0 items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full gradient-cta flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
            </svg>
          </div>
          <div>
            <h2 className="text-title text-on-surface">Reli Assistant</h2>
            <p className="text-label text-on-surface-variant">Your personal knowledge companion</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <InteractionStyleSelector style={interactionStyle} onChange={setInteractionStyle} />
          <ModeToggle mode={chatMode} onChange={setChatMode} />
          <NerdStatsIcon stats={sessionStats} />
          <button
            onClick={() => setCollapsed(c => !c)}
            className="p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
            title={collapsed ? 'Expand chat' : 'Collapse chat'}
            aria-label={collapsed ? 'Expand chat' : 'Collapse chat'}
          >
            <svg className={`w-4 h-4 transition-transform ${collapsed ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile context pills — horizontal scrollable bar */}
      {!collapsed && activeContextThings.length > 0 && (
        <div className="md:hidden shrink-0 px-4 pt-3 pb-2 border-b border-white/5 bg-surface-container-low">
          {/* Label + horizontal divider */}
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant shrink-0">Context Active</span>
            <div className="h-px flex-1 bg-white/5" />
          </div>
          {/* Pills — horizontal scroll */}
          <div className="flex gap-2 overflow-x-auto no-scrollbar">
            {activeContextThings.map(t => (
              <button
                key={t.id}
                onClick={() => openThingDetailStore(t.id)}
                className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-surface-container-low border border-white/5 text-on-surface hover:bg-primary/20 hover:text-primary transition-colors whitespace-nowrap"
              >
                {typeIcon(t.type_hint, thingTypes)} {t.title}
              </button>
            ))}
          </div>
        </div>
      )}

      {!collapsed && (
        <>
          {/* Messages */}
          <div
            ref={scrollContainerRef}
            className="flex-1 overflow-y-auto px-5 py-4"
            onScroll={handleScroll}
          >
            {nudges.length > 0 && (
              <section className="pb-2">
                {nudges.map(nudge => (
                  <NudgeBanner key={nudge.id} nudge={nudge} />
                ))}
              </section>
            )}
            {historyLoading && hasMoreHistory && (
              <div className="flex justify-center py-2">
                <span className="w-4 h-4 border-2 border-on-surface-variant/30 border-t-primary rounded-full animate-spin" />
              </div>
            )}
            {messages.length === 0 && !historyLoading && (
              disclosure.showOnboarding ? (
                <div className="flex flex-col h-full overflow-y-auto px-4 py-6 gap-4">
                  {/* Synthetic welcome message as assistant chat bubble */}
                  <div className="flex gap-3 max-w-[85%]">
                    <div className="w-7 h-7 rounded-full gradient-cta flex-shrink-0 flex items-center justify-center mt-0.5">
                      <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
                      </svg>
                    </div>
                    <div className="bg-surface-container rounded-2xl rounded-tl-sm px-4 py-3">
                      <p className="text-body text-on-surface">
                        Welcome! I'm Reli, your personal knowledge assistant. I help you keep track of everything that matters — projects, tasks, people, and ideas.
                      </p>
                      <p className="text-body text-on-surface mt-2">
                        Let's get to know each other. What are you working on this week?
                      </p>
                    </div>
                  </div>

                  {/* Suggestion pills */}
                  <div className="ml-10 space-y-2">
                    {[
                      "I'm preparing a project proposal due next week",
                      "I have a job interview coming up I need to prep for",
                      "I'm launching a side project and have a lot to track",
                    ].map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => setInput(suggestion)}
                        className="block w-full text-left px-3 py-2 text-body text-on-surface bg-surface-container-high rounded-xl hover:bg-surface-container-high/80 transition-colors"
                      >
                        "{suggestion}"
                      </button>
                    ))}
                  </div>

                  {/* Google import button — show if calendar or Gmail is connected */}
                  {(calendarStatus?.connected || gmailStatus?.connected) && (
                    <div className="ml-10 mt-2 border-t border-on-surface-variant/10 pt-4">
                      <p className="text-label text-on-surface-variant tracking-widest mb-2">OR IMPORT YOUR DATA</p>
                      <button
                        onClick={() => { seedFromGoogle().catch(() => {}) }}
                        disabled={googleSeedLoading}
                        className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-surface-container-high hover:bg-surface-container-high/80 text-body text-on-surface transition-colors disabled:opacity-50"
                      >
                        {googleSeedLoading ? (
                          <span className="w-4 h-4 border-2 border-on-surface/20 border-t-on-surface rounded-full animate-spin" />
                        ) : (
                          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                          </svg>
                        )}
                        {googleSeedLoading ? 'Importing\u2026' : 'Import from Calendar & Gmail'}
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <div className="w-16 h-16 rounded-2xl gradient-cta flex items-center justify-center mb-4">
                    <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
                    </svg>
                  </div>
                  <h3 className="text-title text-on-surface">What's on your mind?</h3>
                  <p className="text-body text-on-surface-variant mt-1 max-w-xs">
                    Try: "Remind me to check the server logs tomorrow" or "I had an idea about the new API design"
                  </p>
                </div>
              )
            )}
            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} speakingId={speakingId} speak={speak} />
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Input area */}
          <div className="px-4 pb-4 pt-2 bg-surface-container-low border-t border-on-surface-variant/10 shrink-0">
            {!isOnline && (
              <div className="mb-2 px-3 py-2 text-sm text-events bg-events/10 border border-events/20 rounded-xl text-center">
                Chat requires an internet connection
              </div>
            )}
            <div className="flex items-end gap-2 bg-surface-container-high rounded-2xl px-3 py-2">
              <textarea
                ref={inputRef}
                rows={1}
                maxLength={10000}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={isOnline ? "Message Reli\u2026" : "Chat unavailable offline"}
                disabled={!isOnline}
                className="flex-1 bg-transparent resize-none outline-none text-body text-on-surface placeholder-on-surface-variant/40 max-h-32 py-1 leading-relaxed disabled:opacity-50 disabled:cursor-not-allowed"
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
                      ? 'bg-ideas text-white animate-pulse'
                      : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high/80'
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
                className="shrink-0 w-8 h-8 rounded-full gradient-cta flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
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
            <p className="text-[10px] text-on-surface-variant/40 text-center mt-1.5 tracking-wide">
              Enter to send · Shift+Enter for new line{speechRecognitionSupported ? ' · mic for voice' : ''}
            </p>
          </div>
        </>
      )}
    </div>
  )
}
