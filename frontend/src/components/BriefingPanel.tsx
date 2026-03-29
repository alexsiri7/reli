import { useState, useCallback } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { Thing, MorningBriefing, SweepFinding, FocusRecommendation } from '../store'
import { typeIcon } from '../utils'

const FINDING_TYPE_ICONS: Record<string, string> = {
  approaching_date: '⏰',
  stale: '💤',
  neglected: '🚨',
  overdue_checkin: '📅',
  orphan: '🔍',
  inconsistency: '⚠️',
  open_question: '❓',
  connection: '🔗',
}

// Snooze options
const SNOOZE_OPTIONS = [
  { label: 'Tomorrow', getDays: () => 1 },
  { label: 'Next week', getDays: () => 7 },
]

function getSnoozeDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().split('T')[0] ?? ''
}

// Snooze dropdown popover
function SnoozeMenu({
  onSnooze,
  onClose,
}: {
  onSnooze: (date: string) => void
  onClose: () => void
}) {
  const [customDate, setCustomDate] = useState('')

  return (
    <div
      className="absolute z-10 top-full left-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-2 min-w-[140px]"
      onMouseLeave={onClose}
    >
      {SNOOZE_OPTIONS.map(opt => (
        <button
          key={opt.label}
          onClick={() => { onSnooze(getSnoozeDate(opt.getDays())); onClose() }}
          className="w-full text-left text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 px-2 py-1.5 rounded"
        >
          {opt.label}
        </button>
      ))}
      <div className="mt-1 pt-1 border-t border-gray-200 dark:border-gray-700">
        <input
          type="date"
          value={customDate}
          min={new Date().toISOString().split('T')[0]}
          onChange={e => setCustomDate(e.target.value)}
          className="w-full text-xs bg-transparent text-gray-700 dark:text-gray-200 px-2 py-1 border border-gray-200 dark:border-gray-600 rounded"
        />
        {customDate && (
          <button
            onClick={() => { onSnooze(customDate); onClose() }}
            className="w-full text-xs text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950 px-2 py-1.5 rounded mt-1 font-medium"
          >
            Pick this date
          </button>
        )}
      </div>
    </div>
  )
}

// Inline action buttons for a Thing item
function ThingActions({
  thingId,
  thingTitle,
  onDone,
  onSnooze,
  onChat,
}: {
  thingId: string
  thingTitle: string
  onDone: (id: string) => void
  onSnooze: (id: string, date: string) => void
  onChat: (title: string) => void
}) {
  const [snoozeOpen, setSnoozeOpen] = useState(false)

  return (
    <div className="relative flex items-center gap-2 mt-1.5 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
      <button
        onClick={e => { e.stopPropagation(); onDone(thingId) }}
        className="text-xs text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-200 font-medium"
        title="Mark done"
      >
        Done
      </button>
      <div className="relative">
        <button
          onClick={e => { e.stopPropagation(); setSnoozeOpen(v => !v) }}
          className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          title="Snooze"
        >
          Snooze
        </button>
        {snoozeOpen && (
          <SnoozeMenu
            onSnooze={date => onSnooze(thingId, date)}
            onClose={() => setSnoozeOpen(false)}
          />
        )}
      </div>
      <button
        onClick={e => { e.stopPropagation(); onChat(thingTitle) }}
        className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
        title="Chat about this"
      >
        Chat
      </button>
    </div>
  )
}

// Animated item wrapper — slides out when dismissed
function AnimatedItem({
  id,
  dismissed,
  children,
}: {
  id: string
  dismissed: boolean
  children: React.ReactNode
}) {
  return (
    <div
      key={id}
      className={`transition-all duration-300 overflow-hidden ${dismissed ? 'max-h-0 opacity-0 mb-0' : 'max-h-40 opacity-100'}`}
    >
      {children}
    </div>
  )
}

function MorningBriefingBlock({ briefing }: { briefing: MorningBriefing }) {
  const { openThingDetail, updateThing, snoozeThing, setMainView, setMobileView, setPendingChatInput } = useStore(
    useShallow(s => ({
      openThingDetail: s.openThingDetail,
      updateThing: s.updateThing,
      snoozeThing: s.snoozeThing,
      setMainView: s.setMainView,
      setMobileView: s.setMobileView,
      setPendingChatInput: s.setPendingChatInput,
    }))
  )
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const handleDone = useCallback(async (id: string) => {
    setDismissed(prev => new Set([...prev, id]))
    await updateThing(id, { active: false })
  }, [updateThing])

  const handleSnooze = useCallback(async (id: string, date: string) => {
    setDismissed(prev => new Set([...prev, id]))
    await snoozeThing(id, date)
  }, [snoozeThing])

  const handleChat = useCallback((title: string) => {
    setPendingChatInput(`Tell me about "${title}"`)
    setMainView('list')
    setMobileView('chat')
  }, [setPendingChatInput, setMainView, setMobileView])

  const c = briefing.content

  const hasPriorities = c.priorities.length > 0
  const hasOverdue = c.overdue.length > 0
  const hasBlockers = c.blockers.length > 0
  const hasFindings = c.findings.length > 0

  return (
    <div className="space-y-4">
      {c.summary && (
        <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{c.summary}</p>
      )}

      {hasOverdue && (
        <div>
          <p className="text-xs font-semibold text-red-500 dark:text-red-400 uppercase tracking-wider mb-1">Overdue</p>
          <div className="space-y-0.5">
            {c.overdue.map(item => (
              <AnimatedItem key={item.thing_id} id={item.thing_id} dismissed={dismissed.has(item.thing_id)}>
                <div
                  className="group flex items-start gap-2 py-1.5 px-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/30 cursor-pointer transition-colors"
                  onClick={() => openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-red-400 text-sm shrink-0 mt-0.5">⚠</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-gray-700 dark:text-gray-200 flex-1">{item.title}</span>
                      <span className="text-xs text-red-400 shrink-0">{item.days_overdue}d</span>
                    </div>
                    <ThingActions
                      thingId={item.thing_id}
                      thingTitle={item.title}
                      onDone={handleDone}
                      onSnooze={handleSnooze}
                      onChat={handleChat}
                    />
                  </div>
                </div>
              </AnimatedItem>
            ))}
          </div>
        </div>
      )}

      {hasPriorities && (
        <div>
          <p className="text-xs font-semibold text-amber-500 dark:text-amber-400 uppercase tracking-wider mb-1">Priorities</p>
          <div className="space-y-0.5">
            {c.priorities.map(item => (
              <AnimatedItem key={item.thing_id} id={item.thing_id} dismissed={dismissed.has(item.thing_id)}>
                <div
                  className="group flex items-start gap-2 py-1.5 px-2 rounded-lg hover:bg-amber-50 dark:hover:bg-amber-950/30 cursor-pointer transition-colors"
                  onClick={() => openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-amber-400 text-sm mt-0.5 shrink-0">⭐</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{item.title}</p>
                    <p className="text-xs text-gray-400 dark:text-gray-500 leading-snug">{item.reasons.join(' · ')}</p>
                    <ThingActions
                      thingId={item.thing_id}
                      thingTitle={item.title}
                      onDone={handleDone}
                      onSnooze={handleSnooze}
                      onChat={handleChat}
                    />
                  </div>
                </div>
              </AnimatedItem>
            ))}
          </div>
        </div>
      )}

      {hasBlockers && (
        <div>
          <p className="text-xs font-semibold text-orange-500 dark:text-orange-400 uppercase tracking-wider mb-1">Blocked</p>
          <div className="space-y-0.5">
            {c.blockers.map(item => (
              <AnimatedItem key={item.thing_id} id={item.thing_id} dismissed={dismissed.has(item.thing_id)}>
                <div
                  className="group flex items-start gap-2 py-1.5 px-2 rounded-lg hover:bg-orange-50 dark:hover:bg-orange-950/30 cursor-pointer transition-colors"
                  onClick={() => openThingDetail(item.thing_id)}
                  role="button"
                >
                  <span className="text-orange-400 text-sm mt-0.5 shrink-0">🚫</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{item.title}</p>
                    {item.blocked_by.length > 0 && (
                      <p className="text-xs text-gray-400 dark:text-gray-500 leading-snug">
                        Blocked by: {item.blocked_by.join(', ')}
                      </p>
                    )}
                    <ThingActions
                      thingId={item.thing_id}
                      thingTitle={item.title}
                      onDone={handleDone}
                      onSnooze={handleSnooze}
                      onChat={handleChat}
                    />
                  </div>
                </div>
              </AnimatedItem>
            ))}
          </div>
        </div>
      )}

      {hasFindings && (
        <div>
          <p className="text-xs font-semibold text-blue-500 dark:text-blue-400 uppercase tracking-wider mb-1">Insights</p>
          <div className="space-y-1">
            {c.findings.slice(0, 5).map(f => (
              <div
                key={f.id}
                className={`flex items-start gap-2 py-1.5 px-2 rounded-lg transition-colors ${f.thing_id ? 'cursor-pointer hover:bg-blue-50 dark:hover:bg-blue-950/30' : ''}`}
                onClick={() => f.thing_id && openThingDetail(f.thing_id)}
                role={f.thing_id ? 'button' : undefined}
              >
                <span className="text-blue-400 text-sm mt-0.5 shrink-0">💡</span>
                <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{f.message}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function FindingsBlock({ findings, briefingThings }: { findings: SweepFinding[], briefingThings: Thing[] }) {
  const { dismissFinding, snoozeFinding, actOnFinding, updateThing, snoozeThing, setMainView, setMobileView, setPendingChatInput } = useStore(
    useShallow(s => ({
      dismissFinding: s.dismissFinding,
      snoozeFinding: s.snoozeFinding,
      actOnFinding: s.actOnFinding,
      updateThing: s.updateThing,
      snoozeThing: s.snoozeThing,
      setMainView: s.setMainView,
      setMobileView: s.setMobileView,
      setPendingChatInput: s.setPendingChatInput,
    }))
  )
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [snoozingFinding, setSnoozingFinding] = useState<string | null>(null)
  const [snoozingThing, setSnoozingThing] = useState<string | null>(null)

  const handleDoneForThing = useCallback(async (id: string) => {
    setDismissed(prev => new Set([...prev, id]))
    await updateThing(id, { active: false })
  }, [updateThing])

  const handleSnoozeForThing = useCallback(async (id: string, date: string) => {
    setDismissed(prev => new Set([...prev, id]))
    await snoozeThing(id, date)
  }, [snoozeThing])

  const handleChat = useCallback((title: string) => {
    setPendingChatInput(`Tell me about "${title}"`)
    setMainView('list')
    setMobileView('chat')
  }, [setPendingChatInput, setMainView, setMobileView])

  if (findings.length === 0 && briefingThings.length === 0) return null

  return (
    <div>
      <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">Daily Briefing</p>
      <div className="space-y-0.5">
        {findings.map(f => {
          const icon = FINDING_TYPE_ICONS[f.finding_type] ?? '📋'
          return (
            <AnimatedItem key={f.id} id={f.id} dismissed={dismissed.has(f.id)}>
              <div className="group px-2 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                <div className="flex items-start gap-2">
                  <span className="text-sm mt-0.5 shrink-0">{icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-700 dark:text-gray-300 leading-snug">{f.message}</p>
                    {f.thing && (
                      <p className="text-xs text-gray-400 mt-0.5 truncate">
                        {typeIcon(f.thing.type_hint)} {f.thing.title}
                      </p>
                    )}
                    <div className="relative flex items-center gap-2 mt-1.5 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                      {f.thing_id && (
                        <button
                          onClick={() => actOnFinding(f)}
                          className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
                        >
                          Open
                        </button>
                      )}
                      {f.thing_id && f.thing && (
                        <button
                          onClick={() => handleChat(f.thing!.title)}
                          className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
                        >
                          Chat
                        </button>
                      )}
                      <div className="relative">
                        <button
                          onClick={() => setSnoozingFinding(snoozingFinding === f.id ? null : f.id)}
                          className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                        >
                          Snooze
                        </button>
                        {snoozingFinding === f.id && (
                          <SnoozeMenu
                            onSnooze={date => {
                              setDismissed(prev => new Set([...prev, f.id]))
                              snoozeFinding(f.id, date)
                            }}
                            onClose={() => setSnoozingFinding(null)}
                          />
                        )}
                      </div>
                      <button
                        onClick={() => {
                          setDismissed(prev => new Set([...prev, f.id]))
                          dismissFinding(f.id)
                        }}
                        className="text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </AnimatedItem>
          )
        })}
        {briefingThings.map(t => (
          <AnimatedItem key={t.id} id={t.id} dismissed={dismissed.has(t.id)}>
            <div className="group px-2 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
              <div
                className="flex items-center gap-2 cursor-pointer"
                onClick={() => useStore.getState().openThingDetail(t.id)}
                role="button"
              >
                <span className="text-sm shrink-0">{typeIcon(t.type_hint)}</span>
                <span className="text-sm text-gray-700 dark:text-gray-200 flex-1 truncate">{t.title}</span>
              </div>
              <div className="relative flex items-center gap-2 mt-1.5 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity ml-6">
                <button
                  onClick={() => handleDoneForThing(t.id)}
                  className="text-xs text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-200 font-medium"
                >
                  Done
                </button>
                <div className="relative">
                  <button
                    onClick={() => setSnoozingThing(snoozingThing === t.id ? null : t.id)}
                    className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                  >
                    Snooze
                  </button>
                  {snoozingThing === t.id && (
                    <SnoozeMenu
                      onSnooze={date => handleSnoozeForThing(t.id, date)}
                      onClose={() => setSnoozingThing(null)}
                    />
                  )}
                </div>
                <button
                  onClick={() => handleChat(t.title)}
                  className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
                >
                  Chat
                </button>
              </div>
            </div>
          </AnimatedItem>
        ))}
      </div>
    </div>
  )
}

function FocusBlock({ recommendations }: { recommendations: FocusRecommendation[] }) {
  const { updateThing, snoozeThing, setMainView, setMobileView, setPendingChatInput } = useStore(
    useShallow(s => ({
      updateThing: s.updateThing,
      snoozeThing: s.snoozeThing,
      setMainView: s.setMainView,
      setMobileView: s.setMobileView,
      setPendingChatInput: s.setPendingChatInput,
    }))
  )
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [snoozingId, setSnoozingId] = useState<string | null>(null)

  const handleDone = useCallback(async (id: string) => {
    setDismissed(prev => new Set([...prev, id]))
    await updateThing(id, { active: false })
  }, [updateThing])

  const handleSnooze = useCallback(async (id: string, date: string) => {
    setDismissed(prev => new Set([...prev, id]))
    await snoozeThing(id, date)
  }, [snoozeThing])

  const handleChat = useCallback((title: string) => {
    setPendingChatInput(`Tell me about "${title}"`)
    setMainView('list')
    setMobileView('chat')
  }, [setPendingChatInput, setMainView, setMobileView])

  if (recommendations.length === 0) return null
  return (
    <div>
      <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">Focus</p>
      <div className="space-y-0.5">
        {recommendations.slice(0, 5).map(rec => (
          <AnimatedItem key={rec.thing.id} id={rec.thing.id} dismissed={dismissed.has(rec.thing.id)}>
            <div
              className={`group flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer transition-colors ${rec.is_blocked ? 'opacity-50' : ''}`}
              onClick={() => useStore.getState().openThingDetail(rec.thing.id)}
              role="button"
            >
              <span className="text-lg leading-none mt-0.5 shrink-0">{typeIcon(rec.thing.type_hint)}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{rec.thing.title}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{rec.reasons.join(' · ')}</p>
                  </div>
                  {rec.is_blocked && (
                    <span className="text-[10px] text-red-400 font-medium mt-1 shrink-0">BLOCKED</span>
                  )}
                </div>
                <div className="relative flex items-center gap-2 mt-1.5 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={e => { e.stopPropagation(); handleDone(rec.thing.id) }}
                    className="text-xs text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-200 font-medium"
                  >
                    Done
                  </button>
                  <div className="relative">
                    <button
                      onClick={e => { e.stopPropagation(); setSnoozingId(snoozingId === rec.thing.id ? null : rec.thing.id) }}
                      className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                    >
                      Snooze
                    </button>
                    {snoozingId === rec.thing.id && (
                      <SnoozeMenu
                        onSnooze={date => { handleSnooze(rec.thing.id, date); setSnoozingId(null) }}
                        onClose={() => setSnoozingId(null)}
                      />
                    )}
                  </div>
                  <button
                    onClick={e => { e.stopPropagation(); handleChat(rec.thing.title) }}
                    className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
                  >
                    Chat
                  </button>
                </div>
              </div>
            </div>
          </AnimatedItem>
        ))}
      </div>
    </div>
  )
}

export function BriefingPanel() {
  const { morningBriefing, morningBriefingLoading, findings, briefing, focusRecommendations, setMainView, setMobileView } = useStore(
    useShallow(s => ({
      morningBriefing: s.morningBriefing,
      morningBriefingLoading: s.morningBriefingLoading,
      findings: s.findings,
      briefing: s.briefing,
      focusRecommendations: s.focusRecommendations,
      setMainView: s.setMainView,
      setMobileView: s.setMobileView,
    }))
  )

  const hasContent = morningBriefing || findings.length > 0 || briefing.length > 0 || focusRecommendations.length > 0

  return (
    <div className="flex flex-col flex-1 min-w-0 min-h-0 bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Morning Briefing</h2>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
            {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <button
          onClick={() => { setMainView('list'); setMobileView('chat') }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950 hover:bg-indigo-100 dark:hover:bg-indigo-900 rounded-lg transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
          Chat
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
        {morningBriefingLoading && !morningBriefing && (
          <div className="space-y-3 animate-pulse">
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2"></div>
            <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-5/6"></div>
          </div>
        )}

        {!hasContent && !morningBriefingLoading && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <span className="text-4xl mb-3">☀️</span>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">No briefing yet</p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Add some things to get your daily briefing</p>
          </div>
        )}

        {morningBriefing && <MorningBriefingBlock briefing={morningBriefing} />}

        {(findings.length > 0 || briefing.length > 0) && (
          <FindingsBlock findings={findings} briefingThings={briefing} />
        )}

        {focusRecommendations.length > 0 && (
          <FocusBlock recommendations={focusRecommendations} />
        )}
      </div>
    </div>
  )
}
