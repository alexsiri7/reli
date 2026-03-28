import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">{title}</h3>
      {children}
    </div>
  )
}

export function WeeklyDigestPanel() {
  const {
    weeklyDigest,
    weeklyDigestLoading,
    weeklyDigestOpen,
    fetchWeeklyDigest,
    closeWeeklyDigest,
  } = useStore(
    useShallow(s => ({
      weeklyDigest: s.weeklyDigest,
      weeklyDigestLoading: s.weeklyDigestLoading,
      weeklyDigestOpen: s.weeklyDigestOpen,
      fetchWeeklyDigest: s.fetchWeeklyDigest,
      closeWeeklyDigest: s.closeWeeklyDigest,
    }))
  )

  useEffect(() => {
    if (weeklyDigestOpen && !weeklyDigest && !weeklyDigestLoading) {
      fetchWeeklyDigest()
    }
  }, [weeklyDigestOpen, weeklyDigest, weeklyDigestLoading, fetchWeeklyDigest])

  if (!weeklyDigestOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={closeWeeklyDigest}>
      <div
        className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 sticky top-0 bg-white dark:bg-gray-900 z-10">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Weekly Digest</h2>
            {weeklyDigest && (
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                Week of {new Date(weeklyDigest.week_start).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })}
              </p>
            )}
          </div>
          <button
            onClick={closeWeeklyDigest}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-5">
          {weeklyDigestLoading ? (
            <div className="space-y-3 animate-pulse">
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-2/3" />
            </div>
          ) : weeklyDigest ? (
            <>
              {/* Summary */}
              <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed bg-indigo-50 dark:bg-indigo-950/30 rounded-lg px-4 py-3 border border-indigo-100 dark:border-indigo-800">
                {weeklyDigest.content.summary}
              </p>

              {/* Completed things */}
              {weeklyDigest.content.things_completed.length > 0 && (
                <Section title={`Completed (${weeklyDigest.content.things_completed.length})`}>
                  <ul className="space-y-1">
                    {weeklyDigest.content.things_completed.map(t => (
                      <li key={t.id} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                        <span className="text-green-500">✓</span>
                        <span>{t.title}</span>
                        {t.type && <span className="text-xs text-gray-400 dark:text-gray-500 capitalize">({t.type})</span>}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* New connections */}
              {weeklyDigest.content.new_connections.length > 0 && (
                <Section title={`New Connections (${weeklyDigest.content.new_connections.length})`}>
                  <ul className="space-y-1">
                    {weeklyDigest.content.new_connections.map((c, i) => (
                      <li key={i} className="text-sm text-gray-700 dark:text-gray-300">
                        <span className="font-medium">{c.from}</span>
                        <span className="text-gray-400 dark:text-gray-500"> {c.relationship} </span>
                        <span className="font-medium">{c.to}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* Preferences learned */}
              {weeklyDigest.content.preferences_learned.length > 0 && (
                <Section title="Preferences Learned">
                  <ul className="space-y-1">
                    {weeklyDigest.content.preferences_learned.map((p, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                        <span>🧠</span>
                        <span>{p.pattern}</span>
                        <span className="text-xs text-gray-400 dark:text-gray-500 capitalize">({p.confidence})</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* Upcoming deadlines */}
              {weeklyDigest.content.upcoming_deadlines.length > 0 && (
                <Section title="Coming Up">
                  <ul className="space-y-1">
                    {weeklyDigest.content.upcoming_deadlines.map(t => (
                      <li key={t.id} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                        <span className="text-orange-400">📅</span>
                        <span>{t.title}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* Open questions */}
              {weeklyDigest.content.open_questions.length > 0 && (
                <Section title="Open Questions">
                  <ul className="space-y-1">
                    {weeklyDigest.content.open_questions.map((q, i) => (
                      <li key={i} className="text-sm text-gray-700 dark:text-gray-300 flex items-start gap-2">
                        <span className="text-gray-400 mt-0.5">?</span>
                        <span>{q}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* Empty state */}
              {weeklyDigest.content.things_completed.length === 0 &&
                weeklyDigest.content.new_connections.length === 0 &&
                weeklyDigest.content.preferences_learned.length === 0 &&
                weeklyDigest.content.upcoming_deadlines.length === 0 && (
                <p className="text-sm text-gray-400 dark:text-gray-500 italic text-center py-4">
                  Reli is keeping watch — check back as the week progresses.
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500">Failed to load digest.</p>
          )}
        </div>
      </div>
    </div>
  )
}
