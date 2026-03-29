import { useState, useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type Thing, type CalendarEvent } from '../store'
import { typeIcon } from '../utils'

type ViewMode = 'week' | 'month'

function typeColor(hint: string | null | undefined): string {
  switch (hint?.toLowerCase()) {
    case 'task': return 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 border-blue-200 dark:border-blue-800'
    case 'project': return 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300 border-purple-200 dark:border-purple-800'
    case 'goal': return 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300 border-green-200 dark:border-green-800'
    case 'event': return 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300 border-orange-200 dark:border-orange-800'
    case 'person': return 'bg-pink-100 text-pink-800 dark:bg-pink-900/40 dark:text-pink-300 border-pink-200 dark:border-pink-800'
    case 'note': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800'
    default: return 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800'
  }
}

function calendarEventColor(): string {
  return 'bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300 border-teal-200 dark:border-teal-800'
}

function startOfWeek(d: Date): Date {
  const day = new Date(d)
  day.setHours(0, 0, 0, 0)
  const dow = day.getDay()
  day.setDate(day.getDate() - dow)
  return day
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

function addWeeks(d: Date, n: number): Date {
  return addDays(d, n * 7)
}

function addMonths(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + n, 1)
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
}

function toDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

interface CalendarItem {
  type: 'thing' | 'event'
  id: string
  title: string
  typeHint?: string | null
  thingId?: string
}

function buildItemMap(things: Thing[], calendarEvents: CalendarEvent[]): Map<string, CalendarItem[]> {
  const map = new Map<string, CalendarItem[]>()

  const add = (key: string, item: CalendarItem) => {
    const existing = map.get(key) ?? []
    existing.push(item)
    map.set(key, existing)
  }

  for (const t of things) {
    if (t.checkin_date) {
      const d = new Date(t.checkin_date)
      if (!isNaN(d.getTime())) {
        add(toDateKey(d), { type: 'thing', id: t.id, title: t.title, typeHint: t.type_hint, thingId: t.id })
      }
    }
    const deadline = t.data?.deadline as string | undefined
    if (deadline) {
      const d = new Date(deadline)
      if (!isNaN(d.getTime())) {
        const key = toDateKey(d)
        const existing = map.get(key) ?? []
        if (!existing.find(i => i.thingId === t.id)) {
          add(key, { type: 'thing', id: t.id, title: t.title, typeHint: t.type_hint, thingId: t.id })
        }
      }
    }
  }

  for (const e of calendarEvents) {
    const dateStr = e.all_day ? e.start : e.start
    const d = new Date(dateStr)
    if (!isNaN(d.getTime())) {
      add(toDateKey(d), { type: 'event', id: e.id, title: e.summary })
    }
  }

  return map
}

function DayCell({
  date,
  items,
  isCurrentMonth,
  isToday,
  compact,
  onItemClick,
}: {
  date: Date
  items: CalendarItem[]
  isCurrentMonth: boolean
  isToday: boolean
  compact: boolean
  onItemClick: (item: CalendarItem) => void
}) {
  const maxVisible = compact ? 2 : 3

  return (
    <div className={`flex flex-col min-h-0 border-b border-r border-gray-100 dark:border-gray-800 ${isCurrentMonth ? '' : 'opacity-40'}`}>
      <div className={`text-xs font-medium px-1.5 pt-1 pb-0.5 ${isToday ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-500 dark:text-gray-400'}`}>
        {isToday ? (
          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-indigo-600 text-white text-xs">
            {date.getDate()}
          </span>
        ) : (
          date.getDate()
        )}
      </div>
      <div className="flex flex-col gap-0.5 px-1 pb-1 overflow-hidden">
        {items.slice(0, maxVisible).map(item => (
          <button
            key={item.type + item.id}
            onClick={() => onItemClick(item)}
            className={`w-full text-left text-[10px] leading-tight px-1 py-0.5 rounded border truncate transition-opacity hover:opacity-80 ${
              item.type === 'event' ? calendarEventColor() : typeColor(item.typeHint)
            }`}
            title={item.title}
          >
            <span className="mr-0.5">{item.type === 'event' ? '📅' : typeIcon(item.typeHint ?? null)}</span>
            {item.title}
          </button>
        ))}
        {items.length > maxVisible && (
          <span className="text-[10px] text-gray-400 dark:text-gray-500 px-1">
            +{items.length - maxVisible} more
          </span>
        )}
      </div>
    </div>
  )
}

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function CalendarView() {
  const { things, calendarEvents, fetchCalendarEvents, calendarStatus, openThingDetail } = useStore(
    useShallow(s => ({
      things: s.things,
      calendarEvents: s.calendarEvents,
      fetchCalendarEvents: s.fetchCalendarEvents,
      calendarStatus: s.calendarStatus,
      openThingDetail: s.openThingDetail,
    }))
  )

  const [viewMode, setViewMode] = useState<ViewMode>('month')
  const [anchor, setAnchor] = useState<Date>(() => new Date())

  useEffect(() => {
    if (calendarStatus.connected) {
      fetchCalendarEvents()
    }
  }, [calendarStatus.connected, fetchCalendarEvents])

  const itemMap = buildItemMap(things, calendarEvents)
  const today = new Date()

  const handleItemClick = (item: CalendarItem) => {
    if (item.thingId) {
      openThingDetail(item.thingId)
    }
  }

  const prev = () => {
    if (viewMode === 'week') setAnchor(a => addWeeks(a, -1))
    else setAnchor(a => addMonths(a, -1))
  }
  const next = () => {
    if (viewMode === 'week') setAnchor(a => addWeeks(a, 1))
    else setAnchor(a => addMonths(a, 1))
  }
  const goToday = () => setAnchor(new Date())

  let days: Date[]
  let headerLabel: string

  if (viewMode === 'week') {
    const ws = startOfWeek(anchor)
    days = Array.from({ length: 7 }, (_, i) => addDays(ws, i))
    headerLabel = `${ws.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${addDays(ws, 6).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`
  } else {
    const ms = startOfMonth(anchor)
    const startDow = ms.getDay()
    const gridStart = addDays(ms, -startDow)
    days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i))
    headerLabel = anchor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-800 shrink-0">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-white w-48 truncate">{headerLabel}</h2>
        <div className="flex items-center gap-1">
          <button
            onClick={prev}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400"
            aria-label="Previous"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <button
            onClick={goToday}
            className="px-2 py-0.5 text-xs rounded border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            Today
          </button>
          <button
            onClick={next}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400"
            aria-label="Next"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
          </button>
        </div>
        <div className="flex items-center gap-1 ml-auto">
          <button
            onClick={() => setViewMode('week')}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              viewMode === 'week'
                ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 font-medium'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            Week
          </button>
          <button
            onClick={() => setViewMode('month')}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              viewMode === 'month'
                ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 font-medium'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            Month
          </button>
        </div>
        {/* Legend */}
        <div className="hidden lg:flex items-center gap-2 text-[10px] text-gray-400 dark:text-gray-500 ml-4">
          <span className={`px-1.5 py-0.5 rounded border ${typeColor('task')}`}>Task</span>
          <span className={`px-1.5 py-0.5 rounded border ${typeColor('project')}`}>Project</span>
          <span className={`px-1.5 py-0.5 rounded border ${typeColor('goal')}`}>Goal</span>
          <span className={`px-1.5 py-0.5 rounded border ${calendarEventColor()}`}>Event</span>
        </div>
      </div>

      {/* Day name headers */}
      <div className="grid grid-cols-7 shrink-0 border-b border-gray-200 dark:border-gray-800">
        {DAY_NAMES.map(name => (
          <div key={name} className="text-center text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500 py-1.5">
            {name}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      <div
        className="flex-1 grid grid-cols-7 min-h-0 overflow-y-auto"
        style={{ gridAutoRows: viewMode === 'week' ? 'minmax(120px, 1fr)' : 'minmax(80px, 1fr)' }}
      >
        {days.map(day => {
          const key = toDateKey(day)
          const items = itemMap.get(key) ?? []
          const isCurrentMonth = viewMode === 'month' ? day.getMonth() === anchor.getMonth() : true
          const isToday = isSameDay(day, today)
          return (
            <DayCell
              key={key}
              date={day}
              items={items}
              isCurrentMonth={isCurrentMonth}
              isToday={isToday}
              compact={viewMode === 'month'}
              onItemClick={handleItemClick}
            />
          )
        })}
      </div>
    </div>
  )
}
