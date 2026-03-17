import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { FocusRecommendation } from '../store'
import { typeIcon } from '../utils'

function FocusCard({ rec }: { rec: FocusRecommendation }) {
  const { thingTypes, openThingDetail } = useStore(useShallow(s => ({
    thingTypes: s.thingTypes,
    openThingDetail: s.openThingDetail,
  })))

  return (
    <div
      className="px-3 py-1.5 cursor-pointer"
      onClick={() => openThingDetail(rec.thing.id)}
      role="button"
    >
      <div className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors px-2">
        <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
          <span className="text-xs font-bold text-gray-400 dark:text-gray-500 tabular-nums w-4 text-right">
            {rec.rank}
          </span>
          <span className="text-base leading-none select-none" title={rec.thing.type_hint ?? 'thing'}>
            {typeIcon(rec.thing.type_hint, thingTypes)}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate leading-snug flex-1">
              {rec.thing.title}
            </p>
            {rec.is_blocked && (
              <span className="shrink-0 text-[10px] font-medium text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 px-1.5 py-0.5 rounded">
                Blocked
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-0.5">
            {rec.reasons.map((reason, i) => (
              <span key={i} className="text-[11px] text-gray-400 dark:text-gray-500 leading-tight">
                {reason}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export function FocusSection() {
  const { focusRecommendations, focusLoading, fetchFocusRecommendations } = useStore(useShallow(s => ({
    focusRecommendations: s.focusRecommendations,
    focusLoading: s.focusLoading,
    fetchFocusRecommendations: s.fetchFocusRecommendations,
  })))

  useEffect(() => {
    fetchFocusRecommendations()
  }, [fetchFocusRecommendations])

  if (focusLoading && focusRecommendations.length === 0) {
    return (
      <section className="py-2 border-b border-gray-100 dark:border-gray-800">
        <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
          Focus
        </h2>
        <div className="px-4 py-2 space-y-1.5 animate-pulse">
          <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
          <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2"></div>
        </div>
      </section>
    )
  }

  if (focusRecommendations.length === 0) return null

  return (
    <section className="py-2 border-b border-gray-100 dark:border-gray-800">
      <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest">
        Focus
      </h2>
      {focusRecommendations.map(rec => (
        <FocusCard key={rec.thing.id} rec={rec} />
      ))}
    </section>
  )
}
