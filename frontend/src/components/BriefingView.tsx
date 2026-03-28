import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { CalendarEvent, MorningBriefingItem, MorningBriefingFinding, SweepFinding, Thing } from '../store'
import { typeIcon } from '../utils'

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

function formatEventTime(event: CalendarEvent): string {
  if (event.all_day) return 'All day'
  const d = new Date(event.start)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function isToday(dateStr: string): boolean {
  const d = new Date(dateStr)
  const now = new Date()
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  )
}

function BriefingCard({
  headerClass,
  headerText,
  children,
}: {
  headerClass: string
  headerText: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden bg-white dark:bg-gray-800 shadow-sm">
      <div className={`px-4 py-2 text-sm font-semibold ${headerClass}`}>
        {headerText}
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-700">
        {children}
      </div>
    </div>
  )
}

function CalendarCardItem({ event }: { event: CalendarEvent }) {
  const time = formatEventTime(event)
  return (
    <div className="px-4 py-2.5 flex items-start gap-3">
      <span className="text-base select-none shrink-0">📅</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{event.summary}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {time}{event.location ? ` · ${event.location}` : ''}
        </p>
      </div>
    </div>
  )
}

function DueTodayItem({ item }: { item: MorningBriefingItem }) {
  const openThingDetail = useStore(s => s.openThingDetail)
  return (
    <div
      className="px-4 py-2.5 flex items-start gap-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
      onClick={() => openThingDetail(item.thing_id)}
      role="button"
    >
      <span className="text-base select-none shrink-0">📋</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{item.title}</p>
        {item.reasons.length > 0 && (
          <p className="text-xs text-gray-500 dark:text-gray-400">{item.reasons.join(' · ')}</p>
        )}
        {item.days_overdue != null && item.days_overdue > 0 && (
          <p className="text-xs text-red-500">{item.days_overdue}d overdue</p>
        )}
      </div>
    </div>
  )
}

function DueTodayThingItem({ thing }: { thing: Thing }) {
  const openThingDetail = useStore(s => s.openThingDetail)
  const thingTypes = useStore(s => s.thingTypes)
  return (
    <div
      className="px-4 py-2.5 flex items-start gap-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
      onClick={() => openThingDetail(thing.id)}
      role="button"
    >
      <span className="text-base select-none shrink-0">{typeIcon(thing.type_hint, thingTypes)}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{thing.title}</p>
        {thing.checkin_date && (
          <p className="text-xs text-indigo-500 dark:text-indigo-400">Check-in due today</p>
        )}
      </div>
    </div>
  )
}

function AttentionItem({ finding, onDismiss }: { finding: SweepFinding; onDismiss: (id: string) => void }) {
  const openThingDetail = useStore(s => s.openThingDetail)
  return (
    <div className="px-4 py-2.5 flex items-start gap-3">
      <span className="text-base select-none shrink-0">⚡</span>
      <div className="flex-1 min-w-0">
        <p
          className={`text-sm text-gray-900 dark:text-gray-100 leading-snug ${finding.thing_id ? 'cursor-pointer hover:underline' : ''}`}
          onClick={() => finding.thing_id && openThingDetail(finding.thing_id)}
        >
          {finding.message}
        </p>
        {finding.thing && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">
            {finding.thing.title}
          </p>
        )}
      </div>
      <button
        onClick={() => onDismiss(finding.id)}
        className="shrink-0 text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
      >
        Dismiss
      </button>
    </div>
  )
}

function INoticedItem({ finding }: { finding: MorningBriefingFinding }) {
  const openThingDetail = useStore(s => s.openThingDetail)
  return (
    <div className="px-4 py-2.5 flex items-start gap-3">
      <span className="text-base select-none shrink-0">📈</span>
      <div className="flex-1 min-w-0">
        <p
          className={`text-sm text-gray-900 dark:text-gray-100 leading-snug ${finding.thing_id ? 'cursor-pointer hover:underline' : ''}`}
          onClick={() => finding.thing_id && openThingDetail(finding.thing_id)}
        >
          {finding.message}
        </p>
        {finding.thing_title && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">{finding.thing_title}</p>
        )}
      </div>
    </div>
  )
}

export function BriefingView() {
  const {
    currentUser,
    calendarStatus,
    calendarEvents,
    morningBriefing,
    briefing,
    findings,
    dismissFinding,
    setMainView,
    setMobileView,
  } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      calendarStatus: s.calendarStatus,
      calendarEvents: s.calendarEvents,
      morningBriefing: s.morningBriefing,
      briefing: s.briefing,
      findings: s.findings,
      dismissFinding: s.dismissFinding,
      setMainView: s.setMainView,
      setMobileView: s.setMobileView,
    }))
  )

  const firstName = currentUser?.name?.split(' ')[0] ?? 'there'
  const today = new Date()
  const dateLabel = today.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })

  // Today's schedule: calendar events for today
  const todayEvents = calendarStatus.connected
    ? calendarEvents.filter(e => isToday(e.start))
    : []

  // Due Today: from morning briefing (overdue + priorities) and briefing (check-in due things)
  const overdueItems: MorningBriefingItem[] = morningBriefing?.content.overdue ?? []
  const priorityItems: MorningBriefingItem[] = morningBriefing?.content.priorities ?? []
  // Deduplicate by thing_id
  const dueTodayIds = new Set<string>()
  const dueItems: MorningBriefingItem[] = []
  for (const item of [...overdueItems, ...priorityItems]) {
    if (!dueTodayIds.has(item.thing_id)) {
      dueTodayIds.add(item.thing_id)
      dueItems.push(item)
    }
  }
  // Also include check-in due things not already in morning briefing
  const checkinDueThings = briefing.filter(t => !dueTodayIds.has(t.id))

  // Needs Attention: sweep findings
  const attentionItems = findings

  // I Noticed: morning briefing findings (insights)
  const iNoticedItems: MorningBriefingFinding[] = morningBriefing?.content.findings ?? []

  const hasSchedule = todayEvents.length > 0
  const hasDueToday = dueItems.length > 0 || checkinDueThings.length > 0
  const hasAttention = attentionItems.length > 0
  const hasINot = iNoticedItems.length > 0

  function handleChatAbout() {
    setMainView('list')
    setMobileView('chat')
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <div className="px-6 pt-6 pb-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shrink-0">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {greeting()}, {firstName}
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Here's what needs your attention today.</p>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{dateLabel}</p>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {!hasSchedule && !hasDueToday && !hasAttention && !hasINot && (
          <div className="text-center py-12 text-gray-400 dark:text-gray-500">
            <p className="text-4xl mb-3">☀️</p>
            <p className="text-base font-medium">You're all caught up!</p>
            <p className="text-sm mt-1">Nothing needs your attention right now.</p>
            <button
              onClick={handleChatAbout}
              className="mt-4 text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Open chat →
            </button>
          </div>
        )}

        {/* Today's Schedule */}
        {hasSchedule && (
          <BriefingCard
            headerClass="text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-950/50"
            headerText="📅 Today's Schedule"
          >
            {todayEvents.map(event => (
              <CalendarCardItem key={event.id} event={event} />
            ))}
          </BriefingCard>
        )}

        {/* Due Today */}
        {hasDueToday && (
          <BriefingCard
            headerClass="text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950/50"
            headerText="📋 Due Today"
          >
            {dueItems.map(item => (
              <DueTodayItem key={item.thing_id} item={item} />
            ))}
            {checkinDueThings.map(thing => (
              <DueTodayThingItem key={thing.id} thing={thing} />
            ))}
          </BriefingCard>
        )}

        {/* Needs Attention */}
        {hasAttention && (
          <BriefingCard
            headerClass="text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/50"
            headerText="⚡ Needs Attention"
          >
            {attentionItems.map(finding => (
              <AttentionItem key={finding.id} finding={finding} onDismiss={dismissFinding} />
            ))}
          </BriefingCard>
        )}

        {/* I Noticed */}
        {hasINot && (
          <BriefingCard
            headerClass="text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-950/50"
            headerText="🧠 I Noticed"
          >
            {iNoticedItems.map(f => (
              <INoticedItem key={f.id} finding={f} />
            ))}
          </BriefingCard>
        )}
      </div>
    </div>
  )
}
