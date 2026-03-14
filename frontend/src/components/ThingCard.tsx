import type { Thing } from '../store'
import { useStore } from '../store'
import { formatDate, isOverdue, typeIcon } from '../utils'

interface Props {
  thing: Thing
}

export function ThingCard({ thing }: Props) {
  const snoozeThing = useStore(s => s.snoozeThing)

  const overdue = isOverdue(thing.checkin_date)
  const dateLabel = formatDate(thing.checkin_date)

  return (
    <div className="flex items-start gap-2 px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 group transition-colors">
      <span className="text-lg leading-none mt-0.5 select-none" title={thing.type_hint ?? 'thing'}>
        {typeIcon(thing.type_hint)}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate leading-snug">
          {thing.title}
        </p>
        {dateLabel && (
          <p className={`text-xs mt-0.5 ${overdue ? 'text-red-500 font-semibold' : 'text-gray-400 dark:text-gray-500'}`}>
            {overdue ? '⚠ ' : ''}{dateLabel}
          </p>
        )}
      </div>
      <button
        onClick={() => snoozeThing(thing.id, 1)}
        title="Snooze 1 day"
        className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-100 dark:hover:bg-indigo-900 hover:text-indigo-700 dark:hover:text-indigo-300 transition-all shrink-0"
      >
        💤
      </button>
    </div>
  )
}
