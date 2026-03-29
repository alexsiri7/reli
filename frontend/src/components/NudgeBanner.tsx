import { useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { ProactiveSurface } from '../store'
import { typeIcon } from '../utils'

function NudgeCard({ surface, onDismiss, onStop, onOpen }: {
  surface: ProactiveSurface
  onDismiss: () => void
  onStop: () => void
  onOpen: () => void
}) {
  const isUrgent = surface.days_away === 0 || surface.days_away === 1
  const { thingTypes } = useStore(useShallow(s => ({ thingTypes: s.thingTypes })))

  return (
    <div
      className={`mx-3 mb-2 rounded-xl overflow-hidden shadow-sm border ${
        isUrgent
          ? 'bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-950/40 dark:to-orange-950/40 border-amber-200 dark:border-amber-800'
          : 'bg-gradient-to-r from-indigo-50 to-blue-50 dark:from-indigo-950/40 dark:to-blue-950/40 border-indigo-200 dark:border-indigo-800'
      }`}
    >
      <div className="px-3 py-2.5">
        <div className="flex items-start gap-2.5">
          <span className="text-xl leading-none mt-0.5 shrink-0 select-none">
            {isUrgent ? '⏰' : '💡'}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className="text-sm select-none">{typeIcon(surface.thing.type_hint, thingTypes)}</span>
              <p
                className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate cursor-pointer hover:underline"
                onClick={onOpen}
                role="button"
              >
                {surface.thing.title}
              </p>
            </div>
            <p className={`text-xs font-medium ${isUrgent ? 'text-amber-700 dark:text-amber-400' : 'text-indigo-600 dark:text-indigo-400'}`}>
              {surface.reason}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 mt-2 pl-8">
          <button
            onClick={onOpen}
            className={`text-xs font-semibold px-2.5 py-1 rounded-md transition-colors ${
              isUrgent
                ? 'bg-amber-500 hover:bg-amber-600 text-white'
                : 'bg-indigo-500 hover:bg-indigo-600 text-white'
            }`}
          >
            Open
          </button>
          <button
            onClick={onDismiss}
            className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
          >
            Dismiss
          </button>
          <button
            onClick={onStop}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 transition-colors ml-auto"
            title="Stop showing this type of reminder"
          >
            Stop these
          </button>
        </div>
      </div>
    </div>
  )
}

export function NudgeBanner() {
  const { proactiveSurfaces, dismissedNudgeKeys, dismissNudge, stopNudge, openThingDetail } = useStore(
    useShallow(s => ({
      proactiveSurfaces: s.proactiveSurfaces,
      dismissedNudgeKeys: s.dismissedNudgeKeys,
      dismissNudge: s.dismissNudge,
      stopNudge: s.stopNudge,
      openThingDetail: s.openThingDetail,
    }))
  )

  // Track how many nudges shown today (max 3)
  const [shownCount] = useState(() => {
    const today = new Date().toDateString()
    const stored = localStorage.getItem('reli-nudge-shown-date')
    if (stored !== today) {
      localStorage.setItem('reli-nudge-shown-date', today)
      localStorage.setItem('reli-nudge-shown-count', '0')
      return 0
    }
    return parseInt(localStorage.getItem('reli-nudge-shown-count') ?? '0', 10)
  })

  const MAX_DAILY = 3

  const visible = proactiveSurfaces.filter(s => {
    const key = `${s.thing.id}:${s.date_key}`
    return !dismissedNudgeKeys.has(key)
  }).slice(0, Math.max(0, MAX_DAILY - shownCount))

  if (visible.length === 0) return null

  // Show only the most urgent nudge (soonest)
  const nudge = visible[0]
  if (!nudge) return null

  return (
    <div className="pt-2" aria-label="Proactive nudge">
      <NudgeCard
        surface={nudge}
        onOpen={() => openThingDetail(nudge.thing.id)}
        onDismiss={() => {
          dismissNudge(nudge.thing.id, nudge.date_key)
          const count = parseInt(localStorage.getItem('reli-nudge-shown-count') ?? '0', 10) + 1
          localStorage.setItem('reli-nudge-shown-count', String(count))
        }}
        onStop={() => {
          stopNudge(nudge.thing.id, nudge.date_key)
        }}
      />
    </div>
  )
}
