import { useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type CalendarEvent, type SweepFinding, type Thing } from '../store'
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

function isToday(dateStr: string): boolean {
  const date = new Date(dateStr)
  const now = new Date()
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  )
}

function ScheduleCard({ events }: { events: CalendarEvent[] }) {
  if (events.length === 0) return null
  return (
    <div className="flex flex-col min-h-0 rounded-xl border border-green-200 dark:border-green-900 bg-white dark:bg-gray-900 overflow-hidden shadow-sm">
      <div className="bg-green-500 dark:bg-green-700 px-4 py-2.5 flex items-center gap-2 shrink-0">
        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 9v7.5" />
        </svg>
        <h3 className="text-sm font-semibold text-white">Today's Schedule</h3>
        <span className="ml-auto text-xs text-green-100">{events.length} event{events.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800">
        {events.map(event => (
          <div key={event.id} className="px-4 py-2.5 hover:bg-green-50 dark:hover:bg-green-950/20 transition-colors">
            <div className="flex items-start gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500 mt-1.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-gray-800 dark:text-gray-200 truncate leading-snug">{event.summary}</p>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{formatEventTime(event)}</p>
                {event.location && (
                  <p className="text-xs text-gray-400 dark:text-gray-500 truncate">{event.location}</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function DueTodayCard({ things }: { things: Thing[] }) {
  if (things.length === 0) return null
  const openThingDetail = useStore.getState().openThingDetail
  return (
    <div className="flex flex-col min-h-0 rounded-xl border border-indigo-200 dark:border-indigo-900 bg-white dark:bg-gray-900 overflow-hidden shadow-sm">
      <div className="bg-indigo-500 dark:bg-indigo-700 px-4 py-2.5 flex items-center gap-2 shrink-0">
        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
        <h3 className="text-sm font-semibold text-white">Due Today</h3>
        <span className="ml-auto text-xs text-indigo-100">{things.length} item{things.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800">
        {things.map(thing => (
          <div
            key={thing.id}
            className="px-4 py-2.5 hover:bg-indigo-50 dark:hover:bg-indigo-950/20 transition-colors cursor-pointer"
            onClick={() => openThingDetail(thing.id)}
            role="button"
          >
            <div className="flex items-center gap-2">
              <span className="text-base leading-none shrink-0">{typeIcon(thing.type_hint)}</span>
              <p className="text-sm text-gray-800 dark:text-gray-200 truncate leading-snug flex-1">{thing.title}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const FINDING_TYPE_ICONS: Record<string, string> = {
  approaching_date: '\u23F0',
  stale: '\u{1F4A4}',
  neglected: '\u{1F6A8}',
  overdue_checkin: '\u{1F4C5}',
  orphan: '\u{1F50D}',
  inconsistency: '\u26A0\uFE0F',
  open_question: '\u2753',
  connection: '\u{1F517}',
}

function NeedsAttentionCard({ findings }: { findings: SweepFinding[] }) {
  if (findings.length === 0) return null
  const openThingDetail = useStore.getState().openThingDetail
  return (
    <div className="flex flex-col min-h-0 rounded-xl border border-amber-200 dark:border-amber-900 bg-white dark:bg-gray-900 overflow-hidden shadow-sm">
      <div className="bg-amber-500 dark:bg-amber-700 px-4 py-2.5 flex items-center gap-2 shrink-0">
        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
        <h3 className="text-sm font-semibold text-white">Needs Attention</h3>
        <span className="ml-auto text-xs text-amber-100">{findings.length} item{findings.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800">
        {findings.map(finding => (
          <div
            key={finding.id}
            className={`px-4 py-2.5 hover:bg-amber-50 dark:hover:bg-amber-950/20 transition-colors ${finding.thing_id ? 'cursor-pointer' : ''}`}
            onClick={() => finding.thing_id && openThingDetail(finding.thing_id)}
            role={finding.thing_id ? 'button' : undefined}
          >
            <div className="flex items-start gap-2">
              <span className="text-sm mt-0.5 shrink-0">{FINDING_TYPE_ICONS[finding.finding_type] ?? '\u{1F4CB}'}</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-700 dark:text-gray-300 leading-snug">{finding.message}</p>
                {finding.thing && (
                  <p className="text-xs text-gray-400 mt-0.5 truncate">
                    {typeIcon(finding.thing.type_hint)} {finding.thing.title}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function INoticedCard({ things }: { things: Thing[] }) {
  if (things.length === 0) return null
  const openThingDetail = useStore.getState().openThingDetail
  return (
    <div className="flex flex-col min-h-0 rounded-xl border border-purple-200 dark:border-purple-900 bg-white dark:bg-gray-900 overflow-hidden shadow-sm">
      <div className="bg-purple-500 dark:bg-purple-700 px-4 py-2.5 flex items-center gap-2 shrink-0">
        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
        </svg>
        <h3 className="text-sm font-semibold text-white">I Noticed</h3>
        <span className="ml-auto text-xs text-purple-100">{things.length} insight{things.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800">
        {things.map(thing => {
          const confidence: number = typeof thing.data?.confidence === 'number' ? thing.data.confidence : 0
          const category: string = typeof thing.data?.category === 'string' ? thing.data.category : ''
          return (
            <div
              key={thing.id}
              className="px-4 py-2.5 hover:bg-purple-50 dark:hover:bg-purple-950/20 transition-colors cursor-pointer"
              onClick={() => openThingDetail(thing.id)}
              role="button"
            >
              <div className="flex items-start gap-2">
                <span className="text-base leading-none shrink-0">⚙️</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 dark:text-gray-200 leading-snug truncate">{thing.title}</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    {confidence >= 0.7 && (
                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950">Strong</span>
                    )}
                    {confidence >= 0.5 && confidence < 0.7 && (
                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950">Moderate</span>
                    )}
                    {confidence < 0.5 && confidence > 0 && (
                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950">Emerging</span>
                    )}
                    {category && (
                      <span className="text-[10px] text-gray-400 dark:text-gray-500 capitalize">{category}</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function BriefingCards() {
  const { currentUser, calendarEvents, briefing, findings, things } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      calendarEvents: s.calendarEvents,
      briefing: s.briefing,
      findings: s.findings,
      things: s.things,
    }))
  )

  // Today's calendar events only
  const todayEvents = useMemo(() => {
    return calendarEvents.filter(e => isToday(e.all_day ? e.start : e.start))
  }, [calendarEvents])

  // Needs Attention: sweep findings (stale, overdue, neglected, etc.)
  const attentionFindings = useMemo(() => {
    return findings.slice(0, 10)
  }, [findings])

  // I Noticed: new preference things (created within last 14 days with evidence)
  const NEW_INSIGHT_WINDOW_MS = 14 * 24 * 60 * 60 * 1000
  const noticedThings = useMemo(() => {
    const now = Date.now()
    return things.filter(t => {
      if (t.type_hint !== 'preference') return false
      const age = now - new Date(t.created_at).getTime()
      if (age > NEW_INSIGHT_WINDOW_MS) return false
      const confidence: number = typeof t.data?.confidence === 'number' ? t.data.confidence : 0
      const evidence: unknown[] = Array.isArray(t.data?.evidence) ? (t.data.evidence as unknown[]) : []
      return confidence >= 0.4 || evidence.length > 0
    })
  }, [things])

  const hasAnyContent = todayEvents.length > 0 || briefing.length > 0 || attentionFindings.length > 0 || noticedThings.length > 0

  const greeting = currentUser ? getGreeting(currentUser.name.split(' ')[0] ?? currentUser.name) : 'Good day'
  const dateLabel = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-gray-50 dark:bg-gray-950 overflow-y-auto md:overflow-hidden p-4 gap-4">
      {/* Greeting header */}
      <div className="shrink-0">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-white">{greeting}</h1>
        <p className="text-sm text-gray-400 dark:text-gray-500">{dateLabel}</p>
      </div>

      {!hasAnyContent ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-4xl mb-3">✨</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">Nothing needs your attention right now.</p>
          </div>
        </div>
      ) : (
        /* 2×2 card grid — each card scrolls internally if content overflows */
        <div className="grid grid-cols-1 md:grid-cols-2 md:grid-rows-2 gap-4 flex-1 md:min-h-0">
          <ScheduleCard events={todayEvents} />
          <DueTodayCard things={briefing} />
          <NeedsAttentionCard findings={attentionFindings} />
          <INoticedCard things={noticedThings} />
        </div>
      )}
    </div>
  )
}
