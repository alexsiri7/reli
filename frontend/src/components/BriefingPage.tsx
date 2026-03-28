import { useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { MorningBriefingItem, MorningBriefingFinding } from '../store'
import { typeIcon } from '../utils'

function snoozeDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

function BriefingItemCard({
  item,
  accentClass,
  icon,
  onOpen,
  onSnooze,
  onDone,
}: {
  item: MorningBriefingItem
  accentClass: string
  icon: string
  onOpen: (id: string) => void
  onSnooze: (id: string, date: string) => void
  onDone: (id: string) => void
}) {
  const [showSnooze, setShowSnooze] = useState(false)

  return (
    <div className="group relative flex items-start gap-3 px-4 py-3 rounded-xl bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 hover:border-gray-200 dark:hover:border-gray-600 transition-all shadow-sm">
      <span className="text-lg leading-none mt-0.5 shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <p
          className="text-sm font-medium text-gray-900 dark:text-gray-100 cursor-pointer hover:text-indigo-600 dark:hover:text-indigo-400 leading-snug"
          onClick={() => onOpen(item.thing_id)}
        >
          {item.title}
        </p>
        {item.reasons.length > 0 && (
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 leading-snug">
            {item.reasons.join(' · ')}
          </p>
        )}
        {item.days_overdue != null && item.days_overdue > 0 && (
          <p className={`text-xs mt-0.5 font-medium ${accentClass}`}>
            {item.days_overdue}d overdue
          </p>
        )}
        {item.blocked_by.length > 0 && (
          <p className="text-xs text-orange-500 dark:text-orange-400 mt-0.5 leading-snug truncate">
            Blocked by: {item.blocked_by.join(', ')}
          </p>
        )}
        {/* Inline actions */}
        <div className="flex items-center gap-3 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => onOpen(item.thing_id)}
            className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
          >
            Open
          </button>
          <button
            onClick={() => onDone(item.thing_id)}
            className="text-xs text-emerald-500 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300 font-medium"
          >
            Done
          </button>
          <div className="relative">
            <button
              onClick={() => setShowSnooze(v => !v)}
              className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
            >
              Snooze
            </button>
            {showSnooze && (
              <div className="absolute left-0 bottom-6 z-10 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg text-xs overflow-hidden min-w-[110px]">
                <button
                  onClick={() => { setShowSnooze(false); onSnooze(item.thing_id, snoozeDate(1)) }}
                  className="w-full text-left px-3 py-1.5 hover:bg-indigo-50 dark:hover:bg-indigo-900/40 text-gray-700 dark:text-gray-200"
                >
                  Tomorrow
                </button>
                <button
                  onClick={() => { setShowSnooze(false); onSnooze(item.thing_id, snoozeDate(7)) }}
                  className="w-full text-left px-3 py-1.5 hover:bg-indigo-50 dark:hover:bg-indigo-900/40 text-gray-700 dark:text-gray-200"
                >
                  Next week
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function FindingCard({
  finding,
  onOpen,
  onDismiss,
}: {
  finding: MorningBriefingFinding
  onOpen: (id: string) => void
  onDismiss: (id: string) => void
}) {
  return (
    <div className="group flex items-start gap-3 px-4 py-3 rounded-xl bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 hover:border-gray-200 dark:hover:border-gray-600 transition-all shadow-sm">
      <span className="text-lg leading-none mt-0.5 shrink-0">💡</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{finding.message}</p>
        {finding.thing_title && (
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">
            {finding.thing_title}
          </p>
        )}
        <div className="flex items-center gap-3 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
          {finding.thing_id && (
            <button
              onClick={() => onOpen(finding.thing_id!)}
              className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
            >
              Open
            </button>
          )}
          <button
            onClick={() => onDismiss(finding.id)}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}

export function BriefingPage() {
  const {
    morningBriefing,
    morningBriefingLoading,
    briefing,
    findings,
    thingTypes,
    setMainView,
    openThingDetail,
    snoozeThing,
    updateThing,
    dismissFinding,
    fetchMorningBriefing,
  } = useStore(useShallow(s => ({
    morningBriefing: s.morningBriefing,
    morningBriefingLoading: s.morningBriefingLoading,
    briefing: s.briefing,
    findings: s.findings,
    thingTypes: s.thingTypes,
    setMainView: s.setMainView,
    openThingDetail: s.openThingDetail,
    snoozeThing: s.snoozeThing,
    updateThing: s.updateThing,
    dismissFinding: s.dismissFinding,
    fetchMorningBriefing: s.fetchMorningBriefing,
  })))

  const handleOpen = (thingId: string) => {
    setMainView('list')
    openThingDetail(thingId)
  }

  const handleSnooze = (thingId: string, date: string) => {
    snoozeThing(thingId, date)
  }

  const handleDone = (thingId: string) => {
    updateThing(thingId, { active: false })
  }

  const handleFindingDismiss = (findingId: string) => {
    dismissFinding(findingId)
  }

  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })

  // Determine content to show
  const c = morningBriefing?.content

  const hasOverdue = (c?.overdue.length ?? 0) > 0
  const hasPriorities = (c?.priorities.length ?? 0) > 0
  const hasBlockers = (c?.blockers.length ?? 0) > 0
  const hasFindings = (c?.findings.length ?? 0) > 0
  const hasBriefingThings = briefing.length > 0
  const hasSweepFindings = findings.length > 0

  const hasAnyContent = hasOverdue || hasPriorities || hasBlockers || hasFindings || hasBriefingThings || hasSweepFindings

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-900">
      <div className="max-w-2xl mx-auto px-4 py-8 pb-16">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {greeting()}.
          </h1>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">{today}</p>
          {c?.summary && (
            <p className="text-base text-gray-600 dark:text-gray-300 mt-3 leading-relaxed">
              {c.summary}
            </p>
          )}
        </div>

        {morningBriefingLoading && !morningBriefing && (
          <div className="space-y-3 animate-pulse">
            <div className="h-16 bg-gray-200 dark:bg-gray-800 rounded-xl" />
            <div className="h-16 bg-gray-200 dark:bg-gray-800 rounded-xl" />
            <div className="h-16 bg-gray-200 dark:bg-gray-800 rounded-xl" />
          </div>
        )}

        {!morningBriefingLoading && !hasAnyContent && (
          <div className="text-center py-16">
            <p className="text-4xl mb-4">✨</p>
            <p className="text-lg font-medium text-gray-700 dark:text-gray-300">Nothing needs your attention today.</p>
            <p className="text-sm text-gray-400 dark:text-gray-500 mt-2">Your morning briefing shows up here once you have things with check-in dates.</p>
            <button
              onClick={() => fetchMorningBriefing()}
              className="mt-4 text-xs text-indigo-500 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300"
            >
              Refresh
            </button>
          </div>
        )}

        {/* TODAY — overdue items */}
        {hasOverdue && (
          <section className="mb-6">
            <h2 className="text-xs font-semibold text-red-500 dark:text-red-400 uppercase tracking-widest mb-3">
              📅 Overdue
            </h2>
            <div className="space-y-2">
              {c!.overdue.map(item => (
                <BriefingItemCard
                  key={item.thing_id}
                  item={item}
                  accentClass="text-red-500 dark:text-red-400"
                  icon="⚠️"
                  onOpen={handleOpen}
                  onSnooze={handleSnooze}
                  onDone={handleDone}
                />
              ))}
            </div>
          </section>
        )}

        {/* Check-in due things (from raw briefing, when no morning briefing) */}
        {hasBriefingThings && !c && (
          <section className="mb-6">
            <h2 className="text-xs font-semibold text-amber-500 dark:text-amber-400 uppercase tracking-widest mb-3">
              📅 Today
            </h2>
            <div className="space-y-2">
              {briefing.map(thing => (
                <div
                  key={thing.id}
                  className="group flex items-start gap-3 px-4 py-3 rounded-xl bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 hover:border-gray-200 dark:hover:border-gray-600 transition-all shadow-sm"
                >
                  <span className="text-lg leading-none mt-0.5 shrink-0">
                    {typeIcon(thing.type_hint, thingTypes)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p
                      className="text-sm font-medium text-gray-900 dark:text-gray-100 cursor-pointer hover:text-indigo-600 dark:hover:text-indigo-400 leading-snug"
                      onClick={() => handleOpen(thing.id)}
                    >
                      {thing.title}
                    </p>
                    <div className="flex items-center gap-3 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => handleOpen(thing.id)}
                        className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
                      >
                        Open
                      </button>
                      <button
                        onClick={() => handleDone(thing.id)}
                        className="text-xs text-emerald-500 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-300 font-medium"
                      >
                        Done
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* NEEDS ATTENTION — priorities + blockers */}
        {(hasPriorities || hasBlockers) && (
          <section className="mb-6">
            <h2 className="text-xs font-semibold text-amber-500 dark:text-amber-400 uppercase tracking-widest mb-3">
              ⚡ Needs Attention
            </h2>
            <div className="space-y-2">
              {c!.priorities.map(item => (
                <BriefingItemCard
                  key={item.thing_id}
                  item={item}
                  accentClass="text-amber-500 dark:text-amber-400"
                  icon="⭐"
                  onOpen={handleOpen}
                  onSnooze={handleSnooze}
                  onDone={handleDone}
                />
              ))}
              {c!.blockers.map(item => (
                <BriefingItemCard
                  key={item.thing_id}
                  item={item}
                  accentClass="text-orange-500 dark:text-orange-400"
                  icon="🚫"
                  onOpen={handleOpen}
                  onSnooze={handleSnooze}
                  onDone={handleDone}
                />
              ))}
            </div>
          </section>
        )}

        {/* I NOTICED — findings */}
        {(hasFindings || hasSweepFindings) && (
          <section className="mb-6">
            <h2 className="text-xs font-semibold text-blue-500 dark:text-blue-400 uppercase tracking-widest mb-3">
              🔍 I Noticed
            </h2>
            <div className="space-y-2">
              {c?.findings.map(f => (
                <FindingCard
                  key={f.id}
                  finding={f}
                  onOpen={handleOpen}
                  onDismiss={handleFindingDismiss}
                />
              ))}
              {!c && findings.map(f => (
                <div
                  key={f.id}
                  className="group flex items-start gap-3 px-4 py-3 rounded-xl bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 hover:border-gray-200 dark:hover:border-gray-600 transition-all shadow-sm"
                >
                  <span className="text-lg leading-none mt-0.5 shrink-0">💡</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{f.message}</p>
                    {f.thing && (
                      <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">
                        {typeIcon(f.thing.type_hint, thingTypes)} {f.thing.title}
                      </p>
                    )}
                    <div className="flex items-center gap-3 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      {f.thing_id && (
                        <button
                          onClick={() => handleOpen(f.thing_id!)}
                          className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium"
                        >
                          Open
                        </button>
                      )}
                      <button
                        onClick={() => handleFindingDismiss(f.id)}
                        className="text-xs text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Footer navigation */}
        <div className="mt-8 pt-6 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between">
          <button
            onClick={() => setMainView('list')}
            className="text-sm text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium flex items-center gap-1"
          >
            All Things
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
            </svg>
          </button>
          <button
            onClick={() => fetchMorningBriefing()}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
          >
            Refresh
          </button>
        </div>
      </div>
    </div>
  )
}
