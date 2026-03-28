import { useStore } from '../store'
import { useShallow } from 'zustand/react/shallow'
import { typeIcon } from '../utils'

const MAX_NUDGES = 3

export function NudgeBanner() {
  const { proactiveSurfaces, dismissedNudgeIds, dismissNudge, stopNudgeType, openThingDetail } = useStore(
    useShallow(s => ({
      proactiveSurfaces: s.proactiveSurfaces,
      dismissedNudgeIds: s.dismissedNudgeIds,
      dismissNudge: s.dismissNudge,
      stopNudgeType: s.stopNudgeType,
      openThingDetail: s.openThingDetail,
    }))
  )

  // Show time-sensitive nudges (today or tomorrow) that haven't been dismissed
  const urgent = proactiveSurfaces
    .filter(s => s.days_away <= 1 && !dismissedNudgeIds.has(`${s.thing.id}:${s.date_key}`))
    .slice(0, MAX_NUDGES)

  if (urgent.length === 0) return null

  return (
    <div className="border-b border-gray-100 dark:border-gray-800 space-y-1 py-2">
      {urgent.map(surface => {
        const key = `${surface.thing.id}:${surface.date_key}`
        return (
          <div
            key={key}
            className="mx-3 rounded-lg border border-amber-200 dark:border-amber-800 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-950/40 dark:to-orange-950/40 px-3 py-2"
          >
            <div className="flex items-start gap-2">
              <span className="text-base shrink-0 mt-0.5" aria-hidden>⏰</span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-amber-800 dark:text-amber-200 leading-snug">
                  {surface.reason}
                </p>
                <p className="text-xs text-amber-700 dark:text-amber-300 truncate mt-0.5">
                  {typeIcon(surface.thing.type_hint)} {surface.thing.title}
                </p>
                <div className="flex items-center gap-2 mt-1.5">
                  <button
                    onClick={() => openThingDetail(surface.thing.id)}
                    className="text-[11px] font-medium text-amber-700 dark:text-amber-300 hover:text-amber-900 dark:hover:text-amber-100 transition-colors"
                  >
                    View
                  </button>
                  <span className="text-amber-300 dark:text-amber-700">·</span>
                  <button
                    onClick={() => dismissNudge(key)}
                    className="text-[11px] text-amber-500 dark:text-amber-500 hover:text-amber-700 dark:hover:text-amber-300 transition-colors"
                  >
                    Dismiss
                  </button>
                  <span className="text-amber-300 dark:text-amber-700">·</span>
                  <button
                    onClick={() => stopNudgeType(surface.thing.id, surface.date_key)}
                    className="text-[11px] text-amber-500 dark:text-amber-500 hover:text-amber-700 dark:hover:text-amber-300 transition-colors"
                  >
                    Stop these
                  </button>
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
