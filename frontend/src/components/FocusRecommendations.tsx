import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { FocusRecommendation } from '../store'
import { typeIcon } from '../utils'

function RecommendationCard({ rec }: { rec: FocusRecommendation }) {
  const { thingTypes, openThingDetail } = useStore(useShallow(s => ({
    thingTypes: s.thingTypes,
    openThingDetail: s.openThingDetail,
  })))

  return (
    <div
      className="group px-3 py-1"
    >
      <div
        className="flex items-start gap-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors px-1 cursor-pointer"
        onClick={() => openThingDetail(rec.thing.id)}
        role="button"
      >
        <span className="text-lg leading-none mt-0.5 select-none" title={rec.thing.type_hint ?? 'thing'}>
          {typeIcon(rec.thing.type_hint, thingTypes)}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate leading-snug">
            {rec.thing.title}
          </p>
          <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-0.5">
            {rec.reasons.map((reason, i) => (
              <span
                key={i}
                className="text-[11px] text-gray-500 dark:text-gray-400 leading-tight"
              >
                {reason}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export function FocusRecommendations() {
  const { focusRecommendations, focusRecommendationsLoading, fetchFocusRecommendations } = useStore(useShallow(s => ({
    focusRecommendations: s.focusRecommendations,
    focusRecommendationsLoading: s.focusRecommendationsLoading,
    fetchFocusRecommendations: s.fetchFocusRecommendations,
  })))
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    fetchFocusRecommendations()
  }, [fetchFocusRecommendations])

  if (!focusRecommendations || (focusRecommendationsLoading && focusRecommendations.length === 0)) {
    return null
  }

  if (focusRecommendations.length === 0) {
    return null
  }

  return (
    <section className="py-2 border-b border-gray-100 dark:border-gray-800">
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest flex items-center gap-1.5 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className={`h-3 w-3 transition-transform ${collapsed ? '' : 'rotate-90'}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span>Focus</span>
        <span className="ml-auto text-[10px] font-normal tabular-nums">{focusRecommendations.length}</span>
      </button>
      {!collapsed && focusRecommendations.map(rec => (
        <RecommendationCard key={rec.thing.id} rec={rec} />
      ))}
    </section>
  )
}
