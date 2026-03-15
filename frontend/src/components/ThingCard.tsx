import { useState, useEffect } from 'react'
import type { Thing } from '../store'
import { useStore } from '../store'
import { formatDate, formatTimestamp, isOverdue, priorityLabel, typeIcon } from '../utils'

interface Relationship {
  id: string
  from_thing_id: string
  to_thing_id: string
  relationship_type: string
  metadata: Record<string, unknown> | null
  created_at: string
}

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
  const things = useStore(s => s.things)
  const thingTypes = useStore(s => s.thingTypes)
  const [showSnooze, setShowSnooze] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [relationships, setRelationships] = useState<Relationship[]>([])
  const [relsLoaded, setRelsLoaded] = useState(false)

  useEffect(() => {
    if (!expanded || relsLoaded) return
    fetch(`/api/things/${thing.id}/relationships`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setRelationships(data))
      .catch(() => setRelationships([]))
      .finally(() => setRelsLoaded(true))
  }, [expanded, relsLoaded, thing.id])

  const overdue = isOverdue(thing.checkin_date)
  const dateLabel = formatDate(thing.checkin_date)

  const handleSnooze = async (days: number) => {
    setShowSnooze(false)
    await snoozeThing(thing.id, snoozeDate(days))
  }

  const children = things.filter(t => t.parent_id === thing.id)
  const parent = thing.parent_id ? things.find(t => t.id === thing.parent_id) : null

  const dataEntries = thing.data ? Object.entries(thing.data) : []

  return (
    <div className="px-3 py-1">
      {/* Collapsed row */}
      <div
        className="relative flex items-start gap-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 group transition-colors cursor-pointer px-1"
        onClick={() => setExpanded(v => !v)}
        role="button"
        aria-expanded={expanded}
      >
        <span className="text-lg leading-none mt-0.5 select-none" title={thing.type_hint ?? 'thing'}>
          {typeIcon(thing.type_hint, thingTypes)}
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
          {thing.type_hint === 'project' && thing.children_count != null && thing.children_count > 0 && (
            <div className="flex items-center gap-1.5 mt-1">
              <div className="flex-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 dark:bg-emerald-400 rounded-full transition-all"
                  style={{ width: `${Math.round(((thing.completed_count ?? 0) / thing.children_count) * 100)}%` }}
                />
              </div>
              <span className="text-[10px] text-gray-400 dark:text-gray-500 tabular-nums whitespace-nowrap">
                {thing.completed_count ?? 0}/{thing.children_count}
              </span>
            </div>
          )}
        </div>

        {/* Expand indicator */}
        <span className={`text-[10px] text-gray-400 dark:text-gray-500 mt-1 transition-transform ${expanded ? 'rotate-90' : ''}`}>
          ▶
        </span>

        <div className="relative shrink-0" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setShowSnooze(v => !v)}
            title="Snooze"
            className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-100 dark:hover:bg-indigo-900 hover:text-indigo-700 dark:hover:text-indigo-300 transition-all"
          >
            💤
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

      {/* Expanded details */}
      {expanded && (
        <div className="ml-8 mt-1 mb-2 space-y-1.5 text-xs text-gray-600 dark:text-gray-400 border-l-2 border-gray-200 dark:border-gray-700 pl-3">
          {/* Priority */}
          <div>{priorityLabel(thing.priority)}</div>

          {/* Type hint */}
          {thing.type_hint && (
            <div className="capitalize">Type: {thing.type_hint}</div>
          )}

          {/* Data / notes */}
          {dataEntries.length > 0 && (
            <div className="space-y-0.5">
              {dataEntries.map(([key, value]) => (
                <div key={key}>
                  <span className="font-medium text-gray-500 dark:text-gray-400">{key}:</span>{' '}
                  <span className="text-gray-700 dark:text-gray-300">
                    {typeof value === 'string' ? value : JSON.stringify(value)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Timestamps */}
          <div className="text-gray-400 dark:text-gray-500">
            Created {formatTimestamp(thing.created_at)}
          </div>
          {thing.updated_at !== thing.created_at && (
            <div className="text-gray-400 dark:text-gray-500">
              Updated {formatTimestamp(thing.updated_at)}
            </div>
          )}

          {/* Parent */}
          {parent && (
            <div>
              Parent: <span className="font-medium text-gray-700 dark:text-gray-300">{typeIcon(parent.type_hint, thingTypes)} {parent.title}</span>
            </div>
          )}

          {/* Children */}
          {children.length > 0 && (
            <div>
              <span className="font-medium">Children:</span>
              <ul className="ml-3 mt-0.5 space-y-0.5">
                {children.map(c => (
                  <li key={c.id}>{typeIcon(c.type_hint, thingTypes)} {c.title}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Relationships / Connections */}
          {relationships.length > 0 && (
            <div>
              <span className="font-medium">Connections:</span>
              <ul className="ml-3 mt-0.5 space-y-0.5">
                {relationships.map(rel => {
                  const otherId = rel.from_thing_id === thing.id ? rel.to_thing_id : rel.from_thing_id
                  const other = things.find(t => t.id === otherId)
                  const direction = rel.from_thing_id === thing.id ? '→' : '←'
                  return (
                    <li key={rel.id} className="flex items-center gap-1">
                      <span className="text-gray-400 dark:text-gray-500">{direction}</span>
                      <span className="italic text-gray-500 dark:text-gray-400">{rel.relationship_type}</span>
                      {other ? (
                        <span className="text-gray-700 dark:text-gray-300">{typeIcon(other.type_hint, thingTypes)} {other.title}</span>
                      ) : (
                        <span className="text-gray-400 dark:text-gray-500">{otherId}</span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {/* Last referenced */}
          {thing.last_referenced && (
            <div className="text-gray-400 dark:text-gray-500">
              Discussed {formatTimestamp(thing.last_referenced)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
