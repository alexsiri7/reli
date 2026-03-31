import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore, type CalendarEvent } from '../store'

function formatEventTime(event: CalendarEvent): string {
  if (event.all_day) return 'All day'
  const start = new Date(event.start)
  if (isNaN(start.getTime())) return ''
  return start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function formatEventDate(event: CalendarEvent): string {
  const dateStr = event.all_day ? event.start : event.start
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return ''
  const now = new Date()
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  const tomorrow = new Date(now)
  tomorrow.setDate(tomorrow.getDate() + 1)
  const isTomorrow =
    date.getFullYear() === tomorrow.getFullYear() &&
    date.getMonth() === tomorrow.getMonth() &&
    date.getDate() === tomorrow.getDate()
  if (isToday) return 'Today'
  if (isTomorrow) return 'Tomorrow'
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

function EventItem({ event }: { event: CalendarEvent }) {
  const time = formatEventTime(event)
  return (
    <div className="px-4 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors">
      <div className="flex items-start gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm text-gray-800 dark:text-gray-200 truncate">{event.summary}</p>
          <p className="text-xs text-gray-400 dark:text-gray-400">{time}</p>
          {event.location && (
            <p className="text-xs text-gray-400 dark:text-gray-400 truncate">{event.location}</p>
          )}
        </div>
      </div>
    </div>
  )
}

export function CalendarSection() {
  const { calendarStatus, calendarEvents, fetchCalendarStatus, fetchCalendarEvents, connectCalendar, disconnectCalendar } = useStore(
    useShallow(s => ({
      calendarStatus: s.calendarStatus,
      calendarEvents: s.calendarEvents,
      fetchCalendarStatus: s.fetchCalendarStatus,
      fetchCalendarEvents: s.fetchCalendarEvents,
      connectCalendar: s.connectCalendar,
      disconnectCalendar: s.disconnectCalendar,
    }))
  )

  useEffect(() => {
    fetchCalendarStatus()
  }, [fetchCalendarStatus])

  useEffect(() => {
    if (calendarStatus.connected) {
      fetchCalendarEvents()
    }
  }, [calendarStatus.connected, fetchCalendarEvents])

  // Not configured — don't show anything
  if (!calendarStatus.configured) return null

  // Configured but not connected — show connect button
  if (!calendarStatus.connected) {
    return (
      <section className="py-2 border-b border-gray-100 dark:border-gray-800">
        <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
          Calendar
        </h2>
        <div className="px-4 py-2">
          <button
            onClick={connectCalendar}
            className="w-full text-xs px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            Connect Google Calendar
          </button>
        </div>
      </section>
    )
  }

  // Group events by date
  const eventsByDate = new Map<string, CalendarEvent[]>()
  for (const event of calendarEvents) {
    const dateLabel = formatEventDate(event)
    const existing = eventsByDate.get(dateLabel) ?? []
    existing.push(event)
    eventsByDate.set(dateLabel, existing)
  }

  return (
    <section className="py-2 border-b border-gray-100 dark:border-gray-800">
      <div className="px-4 pb-1 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
          Calendar
        </h2>
        <button
          onClick={disconnectCalendar}
          className="text-[10px] text-gray-400 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
          title="Disconnect Google Calendar"
        >
          Disconnect
        </button>
      </div>
      {calendarEvents.length === 0 ? (
        <p className="px-4 py-2 text-xs text-gray-400 dark:text-gray-400">
          No upcoming events
        </p>
      ) : (
        Array.from(eventsByDate.entries()).map(([dateLabel, events]) => (
          <div key={dateLabel}>
            <p className="px-4 pt-1 text-[10px] font-medium text-gray-400 dark:text-gray-400 uppercase">
              {dateLabel}
            </p>
            {events.map(event => (
              <EventItem key={event.id} event={event} />
            ))}
          </div>
        ))
      )}
    </section>
  )
}
