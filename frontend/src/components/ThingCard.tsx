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
  const updateThing = useStore(s => s.updateThing)
  const thingTypes = useStore(s => s.thingTypes)
  const openThingDetail = useStore(s => s.openThingDetail)
  const [showSnooze, setShowSnooze] = useState(false)
  const [completing, setCompleting] = useState(false)

  const overdue = isOverdue(thing.checkin_date)
  const dateLabel = formatDate(thing.checkin_date)
  const isTask = thing.type_hint === 'task'

  const handleSnooze = async (days: number) => {
    setShowSnooze(false)
    await snoozeThing(thing.id, snoozeDate(days))
  }

  const handleCheckbox = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (completing) return
    setCompleting(true)
    // Give animation time to play before the item disappears from the list
    await new Promise(r => setTimeout(r, 600))
    await updateThing(thing.id, { active: false })
  }

  return (
    <div
      className="px-3 py-1 transition-all duration-500"
      style={completing ? { opacity: 0.3, transform: 'translateY(4px)' } : undefined}
    >
      <div
        className="relative flex items-start gap-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 group transition-colors cursor-pointer px-1"
        onClick={() => openThingDetail(thing.id)}
        role="button"
      >
        {isTask ? (
          <button
            onClick={handleCheckbox}
            className="shrink-0 mt-0.5 w-4 h-4 rounded border border-gray-300 dark:border-gray-600 hover:border-emerald-500 dark:hover:border-emerald-400 flex items-center justify-center transition-colors"
            title="Mark done"
            aria-label="Mark task done"
          >
            {completing && (
              <svg xmlns="http://www.w3.org/2000/svg" className="w-3 h-3 text-emerald-500" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
            )}
          </button>
        ) : (
          <span className="text-lg leading-none mt-0.5 select-none" title={thing.type_hint ?? 'thing'}>
            {typeIcon(thing.type_hint, thingTypes)}
          </span>
        )}
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-medium truncate leading-snug transition-all duration-300 ${completing ? 'line-through text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-gray-100'}`}>
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
