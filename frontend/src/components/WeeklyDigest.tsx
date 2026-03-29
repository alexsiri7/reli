import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { WeeklyDigestItem } from '../store'

function DigestSection({ title, icon, items, onItemClick }: {
  title: string
  icon: string
  items: WeeklyDigestItem[]
  onItemClick: (thingId: string) => void
}) {
  if (items.length === 0) return null
  return (
    <div className="mb-5">
      <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">
        {icon} {title}
      </h3>
      <ul className="space-y-1">
        {items.map(item => (
          <li key={item.thing_id} className="flex items-center gap-2">
            <button
              onClick={() => onItemClick(item.thing_id)}
              className="text-sm text-gray-800 dark:text-gray-200 hover:text-indigo-600 dark:hover:text-indigo-400 text-left transition-colors flex-1 min-w-0 truncate"
            >
              {item.title}
            </button>
            {item.note && (
              <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">{item.note}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function WeeklyDigest() {
  const { weeklyDigest, weeklyDigestLoading, weeklyDigestOpen, fetchWeeklyDigest, closeWeeklyDigest, openThingDetail } = useStore(
    useShallow(s => ({
      weeklyDigest: s.weeklyDigest,
      weeklyDigestLoading: s.weeklyDigestLoading,
      weeklyDigestOpen: s.weeklyDigestOpen,
      fetchWeeklyDigest: s.fetchWeeklyDigest,
      closeWeeklyDigest: s.closeWeeklyDigest,
      openThingDetail: s.openThingDetail,
    }))
  )

  useEffect(() => {
    if (weeklyDigestOpen && !weeklyDigest) {
      fetchWeeklyDigest()
    }
  }, [weeklyDigestOpen, weeklyDigest, fetchWeeklyDigest])

  if (!weeklyDigestOpen) return null

  const handleItemClick = (thingId: string) => {
    openThingDetail(thingId)
    closeWeeklyDigest()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Weekly Digest"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 dark:bg-black/60 backdrop-blur-sm"
        onClick={closeWeeklyDigest}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-800 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Weekly Digest</h2>
            {weeklyDigest && (
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                Week of {new Date(weeklyDigest.week_start + 'T12:00:00').toLocaleDateString(undefined, { month: 'long', day: 'numeric' })}
              </p>
            )}
          </div>
          <button
            onClick={closeWeeklyDigest}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="Close digest"
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {weeklyDigestLoading && (
            <div className="flex items-center justify-center py-12">
              <div className="h-6 w-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {!weeklyDigestLoading && !weeklyDigest && (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-8">
              No digest available yet.
            </p>
          )}

          {weeklyDigest && (
            <>
              {/* Summary banner */}
              <div className="bg-indigo-50 dark:bg-indigo-950/40 rounded-xl px-4 py-3 mb-5 border border-indigo-100 dark:border-indigo-900">
                <p className="text-sm text-indigo-800 dark:text-indigo-300 leading-snug">
                  {weeklyDigest.content.summary}
                </p>
              </div>

              {/* Stats row */}
              {weeklyDigest.content.stats && (
                <div className="grid grid-cols-4 gap-2 mb-5">
                  {([
                    { key: 'completed_count', label: 'Done', icon: '✅' },
                    { key: 'preferences_count', label: 'Learned', icon: '🧠' },
                    { key: 'upcoming_count', label: 'Upcoming', icon: '📅' },
                    { key: 'open_questions_count', label: 'Questions', icon: '❓' },
                  ] as const).map(({ key, label, icon }) => (
                    <div key={key} className="text-center bg-gray-50 dark:bg-gray-800 rounded-lg py-2 px-1">
                      <div className="text-lg leading-none">{icon}</div>
                      <div className="text-lg font-bold text-gray-900 dark:text-gray-100 mt-0.5">
                        {weeklyDigest.content.stats[key] ?? 0}
                      </div>
                      <div className="text-xs text-gray-400 dark:text-gray-500">{label}</div>
                    </div>
                  ))}
                </div>
              )}

              <DigestSection
                title="Completed"
                icon="✅"
                items={weeklyDigest.content.completed}
                onItemClick={handleItemClick}
              />
              <DigestSection
                title="Learned"
                icon="🧠"
                items={weeklyDigest.content.preferences_learned}
                onItemClick={handleItemClick}
              />
              <DigestSection
                title="Coming Up"
                icon="📅"
                items={weeklyDigest.content.upcoming}
                onItemClick={handleItemClick}
              />

              {weeklyDigest.content.open_questions.length > 0 && (
                <div className="mb-5">
                  <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">
                    ❓ Open Questions
                  </h3>
                  <ul className="space-y-1">
                    {weeklyDigest.content.open_questions.map((q, i) => (
                      <li key={i} className="text-sm text-gray-600 dark:text-gray-400 leading-snug">
                        {q}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
