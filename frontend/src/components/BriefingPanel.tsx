import { useShallow } from 'zustand/react/shallow'
import { useStore, type CalendarEvent, type MorningBriefingItem, type MorningBriefingFinding } from '../store'

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

function formatDate(): string {
  return new Date().toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatEventTime(event: CalendarEvent): string {
  if (event.all_day) return 'All day'
  const start = new Date(event.start)
  const end = new Date(event.end)
  if (isNaN(start.getTime())) return ''
  const startStr = start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  if (isNaN(end.getTime())) return startStr
  const endStr = end.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${startStr} – ${endStr}`
}

function isTodayEvent(event: CalendarEvent): boolean {
  const dateStr = event.all_day ? event.start : event.start
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return false
  const now = new Date()
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  )
}

function CardHeader({ color, icon, title }: { color: 'green' | 'indigo' | 'amber' | 'purple'; icon: string; title: string }) {
  const colorClass = {
    green: 'bg-green-50 dark:bg-green-950/40 text-green-700 dark:text-green-400 border-green-100 dark:border-green-900',
    indigo: 'bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-400 border-indigo-100 dark:border-indigo-900',
    amber: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border-amber-100 dark:border-amber-900',
    purple: 'bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400 border-purple-100 dark:border-purple-900',
  }[color]

  return (
    <div className={`px-4 py-2.5 flex items-center gap-2 border-b text-xs font-semibold uppercase tracking-wider ${colorClass}`}>
      <span>{icon}</span>
      <span>{title}</span>
    </div>
  )
}

function BriefingItemRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-2.5 flex items-center gap-3 border-b border-gray-50 dark:border-gray-800/50 last:border-b-0">
      {children}
    </div>
  )
}

function ActionButton({ label, primary, onClick }: { label: string; primary?: boolean; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 text-xs rounded-md border font-medium transition-colors shrink-0 ${
        primary
          ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 border-indigo-200 dark:border-indigo-800 hover:bg-indigo-100 dark:hover:bg-indigo-950'
          : 'bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
      }`}
    >
      {label}
    </button>
  )
}

function ScheduleCard({ events }: { events: CalendarEvent[] }) {
  if (events.length === 0) return null
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <CardHeader color="green" icon="📅" title="Today's Schedule" />
      {events.map(event => (
        <BriefingItemRow key={event.id}>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">{event.summary}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {formatEventTime(event)}
              {event.location && ` · ${event.location}`}
            </p>
          </div>
        </BriefingItemRow>
      ))}
    </div>
  )
}

function DueTodayCard({ priorities, overdue }: { priorities: MorningBriefingItem[]; overdue: MorningBriefingItem[] }) {
  const items = [...overdue, ...priorities]
  if (items.length === 0) return null
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <CardHeader color="indigo" icon="📋" title="Due Today" />
      {items.map(item => (
        <BriefingItemRow key={item.thing_id}>
          <div className="flex-1 min-w-0">
            <p
              className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate cursor-pointer hover:text-indigo-600 dark:hover:text-indigo-400"
              onClick={() => useStore.getState().openThingDetail(item.thing_id)}
            >
              {item.title}
            </p>
            {item.reasons.length > 0 && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">{item.reasons.join(' · ')}</p>
            )}
            {item.days_overdue != null && item.days_overdue > 0 && (
              <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{item.days_overdue}d overdue</p>
            )}
          </div>
          <div className="flex gap-1.5 shrink-0">
            <ActionButton label="Done" primary />
            <ActionButton label="Snooze" />
          </div>
        </BriefingItemRow>
      ))}
    </div>
  )
}

function NeedsAttentionCard({ blockers, findings }: { blockers: MorningBriefingItem[]; findings: MorningBriefingFinding[] }) {
  if (blockers.length === 0 && findings.length === 0) return null
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <CardHeader color="amber" icon="⚡" title="Needs Attention" />
      {blockers.map(item => (
        <BriefingItemRow key={item.thing_id}>
          <div className="flex-1 min-w-0">
            <p
              className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate cursor-pointer hover:text-amber-600 dark:hover:text-amber-400"
              onClick={() => useStore.getState().openThingDetail(item.thing_id)}
            >
              {item.title}
            </p>
            {item.blocked_by.length > 0 && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">
                Blocked by: {item.blocked_by.join(', ')}
              </p>
            )}
          </div>
          <div className="flex gap-1.5 shrink-0">
            <ActionButton label="Chat about it" />
            <ActionButton label="Dismiss" />
          </div>
        </BriefingItemRow>
      ))}
      {findings.map(f => (
        <BriefingItemRow key={f.id}>
          <div className="flex-1 min-w-0">
            <p
              className={`text-sm font-medium text-gray-800 dark:text-gray-200 leading-snug ${f.thing_id ? 'cursor-pointer hover:text-amber-600 dark:hover:text-amber-400' : ''}`}
              onClick={() => f.thing_id && useStore.getState().openThingDetail(f.thing_id)}
            >
              {f.message}
            </p>
            {f.thing_title && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">{f.thing_title}</p>
            )}
          </div>
          <div className="flex gap-1.5 shrink-0">
            <ActionButton label="Dismiss" />
          </div>
        </BriefingItemRow>
      ))}
    </div>
  )
}

function INoticedCard({ findings }: { findings: MorningBriefingFinding[] }) {
  if (findings.length === 0) return null
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <CardHeader color="purple" icon="🧠" title="I Noticed" />
      {findings.map(f => (
        <BriefingItemRow key={f.id}>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200 leading-snug">{f.message}</p>
          </div>
          <div className="flex gap-1.5 shrink-0">
            <ActionButton label="That's right" primary />
            <ActionButton label="Not really" />
          </div>
        </BriefingItemRow>
      ))}
    </div>
  )
}

export function BriefingPanel() {
  const { currentUser, morningBriefing, calendarEvents, calendarStatus } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      morningBriefing: s.morningBriefing,
      calendarEvents: s.calendarEvents,
      calendarStatus: s.calendarStatus,
    }))
  )

  const firstName = currentUser?.name?.split(' ')[0] ?? 'there'
  const todayEvents = calendarStatus.connected
    ? calendarEvents.filter(isTodayEvent)
    : []

  const content = morningBriefing?.content
  const priorities = content?.priorities ?? []
  const overdue = content?.overdue ?? []
  const blockers = content?.blockers ?? []
  const allFindings = content?.findings ?? []

  // Split findings: lower priority (>= 3) go to "I Noticed", higher priority to "Needs Attention"
  const attentionFindings = allFindings.filter(f => f.priority <= 2)
  const noticedFindings = allFindings.filter(f => f.priority >= 3)

  const hasAnything = todayEvents.length > 0 || priorities.length > 0 || overdue.length > 0 ||
    blockers.length > 0 || allFindings.length > 0

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden bg-gray-50 dark:bg-gray-950">
      {/* Greeting header */}
      <div className="px-6 py-5 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 shrink-0">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {getGreeting()}, {firstName}
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{formatDate()}</p>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {!hasAnything && (
          <div className="text-center py-16 text-gray-400 dark:text-gray-500 text-sm">
            All caught up — no items for today.
          </div>
        )}
        <ScheduleCard events={todayEvents} />
        <DueTodayCard priorities={priorities} overdue={overdue} />
        <NeedsAttentionCard blockers={blockers} findings={attentionFindings} />
        <INoticedCard findings={noticedFindings} />
      </div>
    </div>
  )
}
