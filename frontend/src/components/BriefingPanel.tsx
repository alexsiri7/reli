import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'

export function BriefingPanel() {
  const { morningBriefing, briefing, findings, setRightView, openThingDetail } = useStore(
    useShallow(s => ({
      morningBriefing: s.morningBriefing,
      briefing: s.briefing,
      findings: s.findings,
      setRightView: s.setRightView,
      openThingDetail: s.openThingDetail,
    }))
  )

  return (
    <div className="flex-1 flex flex-col bg-gray-50 dark:bg-gray-900 min-w-0 min-h-0">
      {/* Header */}
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shrink-0 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Briefing</h2>
          <p className="text-xs text-gray-400 dark:text-gray-400">Your daily overview</p>
        </div>
        <button
          onClick={() => setRightView('chat')}
          className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          title="Switch to Chat"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
          Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Morning briefing */}
        {morningBriefing?.content && (() => {
          const c = morningBriefing.content
          const hasPriorities = c.priorities.length > 0
          const hasOverdue = c.overdue.length > 0
          const hasBlockers = c.blockers.length > 0
          const hasFindings = c.findings.length > 0
          const hasContent = hasPriorities || hasOverdue || hasBlockers || hasFindings || c.summary

          if (!hasContent) return null
          return (
            <section className="p-5 border-b border-gray-200 dark:border-gray-800">
              <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest mb-3">Morning Briefing</h3>
              {c.summary && (
                <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed mb-3">{c.summary}</p>
              )}
              {hasOverdue && (
                <div className="mb-3">
                  <p className="text-xs font-medium text-red-500 dark:text-red-400 uppercase tracking-wider mb-1.5">Overdue</p>
                  <div className="space-y-1">
                    {c.overdue.map(item => (
                      <div
                        key={item.thing_id}
                        className="flex items-center gap-2 py-1.5 px-2 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                        onClick={() => openThingDetail(item.thing_id)}
                        role="button"
                      >
                        <span className="text-red-400 text-xs shrink-0">⚠</span>
                        <span className="text-sm text-gray-700 dark:text-gray-200 flex-1 truncate">{item.title}</span>
                        <span className="text-xs text-red-400 shrink-0">{item.days_overdue}d</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {hasPriorities && (
                <div className="mb-3">
                  <p className="text-xs font-medium text-amber-500 dark:text-amber-400 uppercase tracking-wider mb-1.5">Priorities</p>
                  <div className="space-y-1">
                    {c.priorities.map(item => (
                      <div
                        key={item.thing_id}
                        className="flex items-start gap-2 py-1.5 px-2 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                        onClick={() => openThingDetail(item.thing_id)}
                        role="button"
                      >
                        <span className="text-amber-400 text-xs mt-0.5 shrink-0">⭐</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-700 dark:text-gray-200 truncate">{item.title}</p>
                          <p className="text-xs text-gray-400 dark:text-gray-500">{item.reasons.join(' · ')}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {hasBlockers && (
                <div className="mb-3">
                  <p className="text-xs font-medium text-orange-500 dark:text-orange-400 uppercase tracking-wider mb-1.5">Blocked</p>
                  <div className="space-y-1">
                    {c.blockers.map(item => (
                      <div
                        key={item.thing_id}
                        className="flex items-start gap-2 py-1.5 px-2 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                        onClick={() => openThingDetail(item.thing_id)}
                        role="button"
                      >
                        <span className="text-orange-400 text-xs mt-0.5 shrink-0">🚧</span>
                        <p className="text-sm text-gray-700 dark:text-gray-200 flex-1 truncate">{item.title}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )
        })()}

        {/* Daily briefing / sweep findings */}
        {briefing.length > 0 && (
          <section className="p-5 border-b border-gray-200 dark:border-gray-800">
            <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest mb-3">Check-ins Due</h3>
            <div className="space-y-1">
              {briefing.slice(0, 10).map(thing => (
                <div
                  key={thing.id}
                  className="flex items-center gap-2 py-1.5 px-2 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                  onClick={() => openThingDetail(thing.id)}
                  role="button"
                >
                  <span className="text-xs text-gray-400 shrink-0">📅</span>
                  <span className="text-sm text-gray-700 dark:text-gray-200 flex-1 truncate">{thing.title}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Sweep findings */}
        {findings.length > 0 && (
          <section className="p-5">
            <h3 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest mb-3">Insights</h3>
            <div className="space-y-2">
              {findings.slice(0, 5).map(f => (
                <div key={f.id} className="text-sm text-gray-600 dark:text-gray-300 leading-snug">
                  {f.message}
                </div>
              ))}
            </div>
          </section>
        )}

        {!morningBriefing && briefing.length === 0 && findings.length === 0 && (
          <div className="flex flex-col items-center justify-center h-64 text-center px-6">
            <p className="text-4xl mb-3">☀️</p>
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">No briefing yet</p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Add some Things with check-in dates and your briefing will appear here.</p>
          </div>
        )}
      </div>
    </div>
  )
}
