import { useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type CalendarEvent, type ProactiveSurface } from '../store'
import { typeIcon } from '../utils'

// Color by thing type
function typeColor(typeHint: string | null): string {
  switch (typeHint) {
    case 'task': return 'bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 border-blue-200 dark:border-blue-800'
    case 'event': return 'bg-purple-100 dark:bg-purple-900/40 text-purple-800 dark:text-purple-200 border-purple-200 dark:border-purple-800'
    case 'project': return 'bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-200 border-amber-200 dark:border-amber-800'
    case 'goal': return 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-800'
    case 'person': return 'bg-pink-100 dark:bg-pink-900/40 text-pink-800 dark:text-pink-200 border-pink-200 dark:border-pink-800'
    default: return 'bg-gray-100 dark:bg-gray-800/50 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700'
  }
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

function startOfWeek(d: Date): Date {
  const r = new Date(d)
  r.setDate(r.getDate() - r.getDay())
  r.setHours(0, 0, 0, 0)
  return r
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

// ── Items on a given day ──────────────────────────────────────────────────────

function DayItems({ date, events, surfaces, maxVisible = 3 }: {
  date: Date
  events: CalendarEvent[]
  surfaces: ProactiveSurface[]
  maxVisible?: number
}) {
  const openThingDetail = useStore(s => s.openThingDetail)

  const dayEvents = events.filter(e => {
    const d = new Date(e.start)
    return isSameDay(d, date)
  })

  const daySurfaces = surfaces.filter(s => {
    const target = addDays(new Date(), s.days_away)
    return isSameDay(target, date)
  })

  const all = [
    ...dayEvents.map(e => ({ id: e.id, label: e.summary, kind: 'event' as const, event: e })),
    ...daySurfaces.map(s => ({ id: s.thing.id, label: s.thing.title, kind: 'thing' as const, surface: s })),
  ]

  const visible = all.slice(0, maxVisible)
  const overflow = all.length - maxVisible

  return (
    <div className="flex flex-col gap-0.5 mt-1">
      {visible.map(item => (
        <div
          key={item.id}
          title={item.label}
          className={`text-[10px] truncate px-1 py-0.5 rounded border cursor-pointer hover:opacity-80 transition-opacity ${
            item.kind === 'event'
              ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 border-blue-200 dark:border-blue-800'
              : typeColor(item.kind === 'thing' ? item.surface!.thing.type_hint : null)
          }`}
          onClick={() => {
            if (item.kind === 'thing') {
              openThingDetail(item.id)
            }
          }}
        >
          {item.kind === 'thing' ? `${typeIcon(item.surface!.thing.type_hint)} ` : '📅 '}
          {item.label}
        </div>
      ))}
      {overflow > 0 && (
        <div className="text-[10px] text-gray-400 dark:text-gray-500 px-1">+{overflow} more</div>
      )}
    </div>
  )
}

// ── Week view ─────────────────────────────────────────────────────────────────

function WeekView({ anchorDate, events, surfaces }: {
  anchorDate: Date
  events: CalendarEvent[]
  surfaces: ProactiveSurface[]
}) {
  const weekStart = startOfWeek(anchorDate)
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
  const today = new Date()

  const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

  return (
    <div className="flex-1 overflow-auto">
      <div className="grid grid-cols-7 border-b border-gray-200 dark:border-gray-700">
        {days.map((day, i) => (
          <div
            key={i}
            className="p-2 text-center border-r border-gray-100 dark:border-gray-800 last:border-r-0"
          >
            <p className="text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider">{DAY_LABELS[i]}</p>
            <p className={`text-sm font-medium mt-0.5 w-7 h-7 flex items-center justify-center mx-auto rounded-full ${
              isSameDay(day, today)
                ? 'bg-indigo-500 text-white'
                : 'text-gray-700 dark:text-gray-200'
            }`}>
              {day.getDate()}
            </p>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 flex-1">
        {days.map((day, i) => (
          <div
            key={i}
            className={`min-h-32 p-1.5 border-r border-b border-gray-100 dark:border-gray-800 last:border-r-0 ${
              isSameDay(day, today) ? 'bg-indigo-50/30 dark:bg-indigo-950/20' : ''
            }`}
          >
            <DayItems date={day} events={events} surfaces={surfaces} maxVisible={4} />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Month view ────────────────────────────────────────────────────────────────

function MonthView({ anchorDate, events, surfaces }: {
  anchorDate: Date
  events: CalendarEvent[]
  surfaces: ProactiveSurface[]
}) {
  const today = new Date()
  const monthStart = startOfMonth(anchorDate)
  const firstWeekday = monthStart.getDay() // 0 = Sunday
  const daysInMonth = new Date(anchorDate.getFullYear(), anchorDate.getMonth() + 1, 0).getDate()

  // Build grid: pad front with days from prev month
  const cells: (Date | null)[] = []
  for (let i = 0; i < firstWeekday; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(new Date(anchorDate.getFullYear(), anchorDate.getMonth(), d))
  }
  // Pad to full 6-row grid
  while (cells.length % 7 !== 0) cells.push(null)

  const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

  return (
    <div className="flex-1 overflow-auto">
      <div className="grid grid-cols-7 border-b border-gray-200 dark:border-gray-700">
        {DAY_LABELS.map(d => (
          <div key={d} className="p-2 text-center text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider border-r border-gray-100 dark:border-gray-800 last:border-r-0">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((day, i) => (
          <div
            key={i}
            className={`min-h-20 p-1 border-r border-b border-gray-100 dark:border-gray-800 last-of-type:border-r-0 ${
              day && isSameDay(day, today) ? 'bg-indigo-50/30 dark:bg-indigo-950/20' : ''
            } ${!day ? 'bg-gray-50 dark:bg-gray-900/30' : ''}`}
          >
            {day && (
              <>
                <p className={`text-xs font-medium w-5 h-5 flex items-center justify-center rounded-full ${
                  isSameDay(day, today)
                    ? 'bg-indigo-500 text-white'
                    : 'text-gray-600 dark:text-gray-400'
                }`}>
                  {day.getDate()}
                </p>
                <DayItems date={day} events={events} surfaces={surfaces} maxVisible={2} />
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main CalendarView ─────────────────────────────────────────────────────────

export function CalendarView() {
  const { calendarEvents, calendarStatus, proactiveSurfaces, connectCalendar } = useStore(
    useShallow(s => ({
      calendarEvents: s.calendarEvents,
      calendarStatus: s.calendarStatus,
      proactiveSurfaces: s.proactiveSurfaces,
      connectCalendar: s.connectCalendar,
    }))
  )

  const [calView, setCalView] = useState<'week' | 'month'>('week')
  const [anchorDate, setAnchorDate] = useState(() => new Date())

  function navigate(dir: -1 | 1) {
    setAnchorDate(prev => {
      const d = new Date(prev)
      if (calView === 'week') {
        d.setDate(d.getDate() + dir * 7)
      } else {
        d.setMonth(d.getMonth() + dir)
      }
      return d
    })
  }

  const monthLabel = anchorDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  const weekStart = startOfWeek(anchorDate)
  const weekEnd = addDays(weekStart, 6)
  const weekLabel =
    weekStart.getMonth() === weekEnd.getMonth()
      ? `${weekStart.toLocaleDateString(undefined, { month: 'long' })} ${weekStart.getDate()}–${weekEnd.getDate()}, ${weekStart.getFullYear()}`
      : `${weekStart.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${weekEnd.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-800 shrink-0">
        <button
          onClick={() => navigate(-1)}
          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition-colors"
          aria-label="Previous"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <button
          onClick={() => setAnchorDate(new Date())}
          className="text-sm font-semibold text-gray-800 dark:text-gray-100 min-w-0 flex-1 text-left truncate hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
        >
          {calView === 'week' ? weekLabel : monthLabel}
        </button>
        <button
          onClick={() => navigate(1)}
          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition-colors"
          aria-label="Next"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>

        {/* Week / Month toggle */}
        <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden shrink-0">
          <button
            onClick={() => setCalView('week')}
            className={`px-2.5 py-1 text-xs font-medium transition-colors ${
              calView === 'week'
                ? 'bg-indigo-500 text-white'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            Week
          </button>
          <button
            onClick={() => setCalView('month')}
            className={`px-2.5 py-1 text-xs font-medium transition-colors ${
              calView === 'month'
                ? 'bg-indigo-500 text-white'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            Month
          </button>
        </div>

        {/* Connect button if calendar configured but not connected */}
        {calendarStatus.configured && !calendarStatus.connected && (
          <button
            onClick={connectCalendar}
            className="shrink-0 text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            Connect Calendar
          </button>
        )}
      </div>

      {/* Calendar grid */}
      {calView === 'week' ? (
        <WeekView anchorDate={anchorDate} events={calendarEvents} surfaces={proactiveSurfaces} />
      ) : (
        <MonthView anchorDate={anchorDate} events={calendarEvents} surfaces={proactiveSurfaces} />
      )}

      {/* Legend */}
      <div className="flex items-center gap-3 px-4 py-2 border-t border-gray-100 dark:border-gray-800 text-[10px] text-gray-400 dark:text-gray-500 shrink-0">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-blue-300 dark:bg-blue-800 inline-block" /> Calendar events</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-200 dark:bg-amber-900 inline-block" /> Things with dates</span>
      </div>
    </div>
  )
}
