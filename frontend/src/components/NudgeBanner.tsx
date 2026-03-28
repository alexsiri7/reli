import { useStore } from '../store'
import { useShallow } from 'zustand/react/shallow'
import type { Nudge } from '../store'

function NudgeCard({ nudge }: { nudge: Nudge }) {
  const { dismissNudge, openThingDetail } = useStore(
    useShallow(s => ({ dismissNudge: s.dismissNudge, openThingDetail: s.openThingDetail }))
  )

  const handleAction = () => {
    if (nudge.thing_id) openThingDetail(nudge.thing_id)
    else if (nudge.action_url) window.open(nudge.action_url, '_blank')
    dismissNudge(nudge.id, 'dismiss')
  }

  const icon = nudge.source === 'proactive' ? '📅' : nudge.source === 'sweep' ? '💡' : '🔔'

  return (
    <div className="flex items-start gap-3 px-4 py-3 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/40 dark:to-purple-950/40 border border-indigo-100 dark:border-indigo-800 rounded-lg">
      <span className="text-lg shrink-0 mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-800 dark:text-gray-200 leading-snug">{nudge.message}</p>
        <div className="flex items-center gap-2 mt-2">
          {nudge.action_label && (
            <button
              onClick={handleAction}
              className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 transition-colors"
            >
              {nudge.action_label} →
            </button>
          )}
          <button
            onClick={() => dismissNudge(nudge.id, 'dismiss')}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          >
            Dismiss
          </button>
          <button
            onClick={() => dismissNudge(nudge.id, 'stop-these')}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 transition-colors"
          >
            Stop these
          </button>
        </div>
      </div>
    </div>
  )
}

export function NudgeBanner() {
  const nudges = useStore(s => s.nudges)

  if (nudges.length === 0) return null

  return (
    <div className="flex flex-col gap-2 px-3 pt-3 pb-0">
      {nudges.map(nudge => (
        <NudgeCard key={nudge.id} nudge={nudge} />
      ))}
    </div>
  )
}
