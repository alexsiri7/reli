import { useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type CalendarEvent, type SweepFinding, type Thing, type MorningBriefingFinding } from '../store'
import { typeIcon } from '../utils'

function getGreeting(name: string): string {
  const hour = new Date().getHours()
  if (hour < 12) return `Good morning, ${name}`
  if (hour < 17) return `Good afternoon, ${name}`
  return `Good evening, ${name}`
}

function formatEventTime(event: CalendarEvent): string {
  if (event.all_day) return 'All day'
  const start = new Date(event.start)
  if (isNaN(start.getTime())) return ''
  return start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function snoozeDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

function SnoozeMenu({ onSelect, onClose }: { onSelect: (days: number) => void; onClose: () => void }) {
  return (
    <div
      className="absolute right-0 top-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-20 py-1 min-w-[7rem]"
      onMouseLeave={onClose}
    >
      <button
        className="w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
        onClick={() => onSelect(1)}
      >
        Tomorrow
      </button>
      <button
        className="w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
        onClick={() => onSelect(7)}
      >
        Next week
      </button>
    </div>
  )
}

function ThingRow({ thing, onDone, onSnooze, onChat }: {
  thing: Thing
  onDone: () => void
  onSnooze: (days: number) => void
  onChat: () => void
}) {
  const [snoozeOpen, setSnoozeOpen] = useState(false)
  const openThingDetail = useStore(s => s.openThingDetail)
  return (
    <div className="group flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
      <span className="text-base shrink-0">{typeIcon(thing.type_hint)}</span>
      <button
        className="flex-1 text-sm text-gray-700 dark:text-gray-200 text-left truncate hover:text-indigo-600 dark:hover:text-indigo-400"
        onClick={() => openThingDetail(thing.id)}
      >
        {thing.title}
      </button>
      <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onChat}
          className="px-2 py-0.5 text-xs rounded-md bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:bg-indigo-900/30 dark:text-indigo-400 dark:hover:bg-indigo-900/60 transition-colors"
          title="Chat about it"
        >
          Chat
        </button>
        <button
          onClick={onDone}
          className="px-2 py-0.5 text-xs rounded-md bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/40 dark:text-green-400 dark:hover:bg-green-900/70 transition-colors"
          title="Mark done"
        >
          Done
        </button>
        <div className="relative">
          <button
            onClick={() => setSnoozeOpen(v => !v)}
            className="px-2 py-0.5 text-xs rounded-md bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600 transition-colors"
            title="Snooze"
          >
            Snooze
          </button>
          {snoozeOpen && (
            <SnoozeMenu
              onSelect={days => { onSnooze(days); setSnoozeOpen(false) }}
              onClose={() => setSnoozeOpen(false)}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function FindingRow({ finding, onDismiss, onSnooze }: {
  finding: SweepFinding
  onDismiss: () => void
  onSnooze: (days: number) => void
}) {
  const [snoozeOpen, setSnoozeOpen] = useState(false)
  const openThingDetail = useStore(s => s.openThingDetail)
  return (
    <div className="group flex items-start gap-3 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
      <span className="text-sm shrink-0 mt-0.5 text-amber-500">⚡</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{finding.message}</p>
        {finding.thing && (
          <button
            className="text-xs text-indigo-500 hover:underline mt-0.5"
            onClick={() => openThingDetail(finding.thing!.id)}
          >
            {finding.thing.title}
          </button>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
        <div className="relative">
          <button
            onClick={() => setSnoozeOpen(v => !v)}
            className="px-2 py-0.5 text-xs rounded-md bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600 transition-colors"
            title="Snooze"
          >
            Snooze
          </button>
          {snoozeOpen && (
            <SnoozeMenu
              onSelect={days => { onSnooze(days); setSnoozeOpen(false) }}
              onClose={() => setSnoozeOpen(false)}
            />
          )}
        </div>
        <button
          onClick={onDismiss}
          className="px-2 py-0.5 text-xs rounded-md bg-red-50 text-red-500 hover:bg-red-100 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50 transition-colors"
          title="Dismiss"
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

function NoticedRow({ finding }: { finding: MorningBriefingFinding }) {
  const openThingDetail = useStore(s => s.openThingDetail)
  return (
    <div className="flex items-start gap-3 px-4 py-2.5">
      <span className="text-sm shrink-0 mt-0.5 text-purple-500">✦</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-700 dark:text-gray-200 leading-snug">{finding.message}</p>
        {finding.thing_id && finding.thing_title && (
          <button
            className="text-xs text-indigo-500 hover:underline mt-0.5"
            onClick={() => openThingDetail(finding.thing_id!)}
          >
            {finding.thing_title}
          </button>
        )}
      </div>
    </div>
  )
}

export function BriefingPanel() {
  const {
    currentUser,
    morningBriefing,
    briefing,
    findings,
    calendarEvents,
    setMainView,
    setMobileView,
    openThingDetail,
    snoozeThing,
    updateThing,
    dismissFinding,
    snoozeFinding,
  } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      morningBriefing: s.morningBriefing,
      briefing: s.briefing,
      findings: s.findings,
      calendarEvents: s.calendarEvents,
      setMainView: s.setMainView,
      setMobileView: s.setMobileView,
      openThingDetail: s.openThingDetail,
      snoozeThing: s.snoozeThing,
      updateThing: s.updateThing,
      dismissFinding: s.dismissFinding,
      snoozeFinding: s.snoozeFinding,
    }))
  )

  const [donePending, setDonePending] = useState<Set<string>>(new Set())

  const firstName = currentUser?.name?.split(' ')[0] ?? 'there'
  const greeting = getGreeting(firstName)

  const todayEvents = calendarEvents.filter(e => {
    if (!e.start) return false
    const start = new Date(e.start)
    const now = new Date()
    return (
      start.getFullYear() === now.getFullYear() &&
      start.getMonth() === now.getMonth() &&
      start.getDate() === now.getDate()
    )
  })

  const visibleBriefing = briefing.filter(t => !donePending.has(t.id))
  const noticedFindings: MorningBriefingFinding[] = morningBriefing?.content.findings ?? []

  const hasSummary = morningBriefing?.content.summary
  const hasContent = todayEvents.length > 0 || visibleBriefing.length > 0 || findings.length > 0 || noticedFindings.length > 0

  function handleThingDone(id: string) {
    setDonePending(s => new Set([...s, id]))
    updateThing(id, { active: false })
  }

  function handleThingSnooze(id: string, days: number) {
    snoozeThing(id, snoozeDate(days))
  }

  function handleThingChat(id: string) {
    openThingDetail(id)
    setMainView('list')
    setMobileView('chat')
  }

  function goToChat() {
    setMainView('list')
    setMobileView('chat')
  }

  return (
    <div className="flex-1 flex flex-col bg-gray-50 dark:bg-gray-900 min-w-0 min-h-0">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shrink-0">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-800 dark:text-gray-100">{greeting}</h2>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
              {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
          </div>
          <button
            onClick={goToChat}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
            title="Open chat"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
            </svg>
            Chat
          </button>
        </div>
        {/* NL Summary */}
        {hasSummary && (
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-2 leading-relaxed">
            {morningBriefing!.content.summary}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {!hasContent ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 px-8 text-center">
            <div className="text-3xl">☀️</div>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Nothing needs your attention today.</p>
            <p className="text-xs text-gray-400 dark:text-gray-500">Enjoy your day — Reli is watching.</p>
            <button
              onClick={goToChat}
              className="mt-2 text-xs text-indigo-500 hover:underline"
            >
              Open chat
            </button>
          </div>
        ) : (
          <>
            {/* Today's schedule */}
            {todayEvents.length > 0 && (
              <section className="pt-4">
                <div className="px-4 pb-1.5 flex items-center gap-2">
                  <span className="text-xs font-semibold text-green-600 dark:text-green-400 uppercase tracking-widest">Today</span>
                </div>
                <div className="divide-y divide-gray-100 dark:divide-gray-800">
                  {todayEvents.map(event => (
                    <div key={event.id} className="flex items-center gap-3 px-4 py-2.5">
                      <span className="text-sm shrink-0">📅</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-700 dark:text-gray-200 truncate">{event.summary}</p>
                        {!event.all_day && (
                          <p className="text-xs text-gray-400 dark:text-gray-500">{formatEventTime(event)}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Due things */}
            {visibleBriefing.length > 0 && (
              <section className="pt-4">
                <div className="px-4 pb-1.5">
                  <span className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-widest">Due</span>
                </div>
                <div className="divide-y divide-gray-100 dark:divide-gray-800">
                  {visibleBriefing.map(thing => (
                    <ThingRow
                      key={thing.id}
                      thing={thing}
                      onDone={() => handleThingDone(thing.id)}
                      onSnooze={days => handleThingSnooze(thing.id, days)}
                      onChat={() => handleThingChat(thing.id)}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* Sweep findings / attention */}
            {findings.length > 0 && (
              <section className="pt-4">
                <div className="px-4 pb-1.5">
                  <span className="text-xs font-semibold text-amber-500 dark:text-amber-400 uppercase tracking-widest">Attention</span>
                </div>
                <div className="divide-y divide-gray-100 dark:divide-gray-800">
                  {findings.slice(0, 5).map(finding => (
                    <FindingRow
                      key={finding.id}
                      finding={finding}
                      onDismiss={() => dismissFinding(finding.id)}
                      onSnooze={days => snoozeFinding(finding.id, snoozeDate(days))}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* I Noticed — preference learnings from morning briefing */}
            {noticedFindings.length > 0 && (
              <section className="pt-4">
                <div className="px-4 pb-1.5">
                  <span className="text-xs font-semibold text-purple-500 dark:text-purple-400 uppercase tracking-widest">I Noticed</span>
                </div>
                <div className="divide-y divide-gray-100 dark:divide-gray-800">
                  {noticedFindings.map(finding => (
                    <NoticedRow key={finding.id} finding={finding} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}
