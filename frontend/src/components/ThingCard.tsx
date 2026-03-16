import { useState } from 'react'
import type { Thing } from '../store'
import { useStore } from '../store'
import { formatDate, isOverdue, typeIcon } from '../utils'

interface Props {
  thing: Thing
}

function snoozeDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

export function ThingCard({ thing }: Props) {
  const snoozeThing = useStore(s => s.snoozeThing)
  const thingTypes = useStore(s => s.thingTypes)
  const openThingDetail = useStore(s => s.openThingDetail)
  const [showSnooze, setShowSnooze] = useState(false)

  const overdue = isOverdue(thing.checkin_date)
  const dateLabel = formatDate(thing.checkin_date)

  const handleSnooze = async (days: number) => {
    setShowSnooze(false)
    await snoozeThing(thing.id, snoozeDate(days))
  }

  return (
    <div className="px-3 py-1">
      <div
        className="relative flex items-start gap-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 group transition-colors cursor-pointer px-1"
        onClick={() => openThingDetail(thing.id)}
        role="button"
      >
        <span className="text-lg leading-none mt-0.5 select-none" title={thing.type_hint ?? 'thing'}>
          {typeIcon(thing.type_hint, thingTypes)}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate leading-snug">
            {thing.title}
          </p>
          {dateLabel && (
            <p className={`text-xs mt-0.5 ${overdue ? 'text-red-500 font-semibold' : 'text-gray-400 dark:text-gray-400'}`}>
              {overdue ? '\u{26A0} ' : ''}{dateLabel}
            </p>
          )}
          {thing.type_hint === 'project' && thing.children_count != null && thing.children_count > 0 && (
            <div className="flex items-center gap-1.5 mt-1">
              <div className="flex-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 dark:bg-emerald-400 rounded-full transition-all"
                  style={{ width: `${Math.round(((thing.completed_count ?? 0) / thing.children_count) * 100)}%` }}
                />
              </div>
              <span className="text-[10px] text-gray-400 dark:text-gray-400 tabular-nums whitespace-nowrap">
                {thing.completed_count ?? 0}/{thing.children_count}
              </span>
            </div>
          )}
        </div>

        <div className="relative shrink-0" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setShowSnooze(v => !v)}
            title="Snooze"
            className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-100 dark:hover:bg-indigo-900 hover:text-indigo-700 dark:hover:text-indigo-300 transition-all"
          >
            {'\u{1F4A4}'}
          </button>
          {showSnooze && (
            <div className="absolute right-0 top-7 z-10 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg text-xs overflow-hidden min-w-[110px]">
              <button
                onClick={() => handleSnooze(1)}
                className="w-full text-left px-3 py-1.5 hover:bg-indigo-50 dark:hover:bg-indigo-900/40 text-gray-700 dark:text-gray-200"
              >
                Tomorrow
              </button>
              <button
                onClick={() => handleSnooze(7)}
                className="w-full text-left px-3 py-1.5 hover:bg-indigo-50 dark:hover:bg-indigo-900/40 text-gray-700 dark:text-gray-200"
              >
                Next week
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
