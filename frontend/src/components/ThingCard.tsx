import { useState, useRef, useEffect } from 'react'
import type { Thing } from '../store'
import { useStore } from '../store'
import { formatDate, isOverdue, typeIcon } from '../utils'

interface Props {
  thing: Thing
  onComplete?: (thing: Thing) => void
}

function snoozeDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  d.setHours(0, 0, 0, 0)
  return d.toISOString()
}

export function ThingCard({ thing, onComplete }: Props) {
  const snoozeThing = useStore(s => s.snoozeThing)
  const updateThing = useStore(s => s.updateThing)
  const thingTypes = useStore(s => s.thingTypes)
  const openThingDetail = useStore(s => s.openThingDetail)
  const [showSnooze, setShowSnooze] = useState(false)
  const [completing, setCompleting] = useState(false)
  const isMounted = useRef(true)
  useEffect(() => () => { isMounted.current = false }, [])

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
    // onComplete reflects optimistic UI state — mirrors how updateThing handles
    // offline/error cases (swallows errors, sets global error state). The
    // in-memory completedTasks list auto-corrects on reload.
    if (isMounted.current) onComplete?.(thing)
  }

  return (
    <div
      className="px-3 py-1 transition-all duration-500"
      style={completing ? { opacity: 0, transform: 'translateY(32px)', pointerEvents: 'none' } : undefined}
    >
      <div
        className="relative flex items-start gap-2 py-1.5 rounded-lg hover:bg-surface-container-high group transition-colors cursor-pointer px-2"
        onClick={() => openThingDetail(thing.id)}
        role="button"
      >
        {isTask ? (
          <button
            onClick={handleCheckbox}
            className="shrink-0 mt-0.5 w-4 h-4 rounded border border-on-surface-variant/30 hover:border-projects flex items-center justify-center transition-colors"
            title="Mark done"
            aria-label="Mark task done"
          >
            {completing && (
              <svg xmlns="http://www.w3.org/2000/svg" className="w-3 h-3 text-projects" viewBox="0 0 20 20" fill="currentColor">
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
          <p className={`text-sm font-medium truncate leading-snug transition-all duration-300 ${completing ? 'line-through text-on-surface-variant' : 'text-on-surface'}`}>
            {thing.title}
          </p>
          {dateLabel && (
            <p className={`text-xs mt-0.5 ${overdue ? 'text-ideas font-semibold' : 'text-on-surface-variant'}`}>
              {overdue ? '\u{26A0} ' : ''}{dateLabel}
            </p>
          )}
          {thing.type_hint === 'project' && thing.children_count != null && thing.children_count > 0 && (
            <div className="flex items-center gap-1.5 mt-1">
              <div className="flex-1 h-1.5 bg-surface-container-high rounded-full overflow-hidden">
                <div
                  className="h-full bg-projects rounded-full transition-all"
                  style={{ width: `${Math.round(((thing.completed_count ?? 0) / thing.children_count) * 100)}%` }}
                />
              </div>
              <span className="text-[10px] text-on-surface-variant tabular-nums whitespace-nowrap">
                {thing.completed_count ?? 0}/{thing.children_count}
              </span>
            </div>
          )}
        </div>

        <div className="relative shrink-0" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setShowSnooze(v => !v)}
            title="Snooze"
            className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant hover:bg-primary-container hover:text-on-surface transition-all"
          >
            {'\u{1F4A4}'}
          </button>
          {showSnooze && (
            <div className="absolute right-0 top-7 z-10 bg-surface-container-high border border-on-surface-variant/10 rounded-lg shadow-lg text-xs overflow-hidden min-w-[110px]">
              <button
                onClick={() => handleSnooze(1)}
                className="w-full text-left px-3 py-1.5 hover:bg-primary-container/40 text-on-surface"
              >
                Tomorrow
              </button>
              <button
                onClick={() => handleSnooze(7)}
                className="w-full text-left px-3 py-1.5 hover:bg-primary-container/40 text-on-surface"
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
