import { useStore, type Nudge } from '../store'
import { typeIcon } from '../utils'

interface NudgeBannerProps {
  nudge: Nudge
}

export function NudgeBanner({ nudge }: NudgeBannerProps) {
  const { dismissNudge, stopNudgeType, openThingDetail } = useStore.getState()

  const handlePrimaryAction = () => {
    if (nudge.thing_id) {
      openThingDetail(nudge.thing_id)
    }
  }

  return (
    <div className="mx-0 mb-2 shrink-0 rounded-xl border border-indigo-200 dark:border-indigo-800 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/40 dark:to-purple-950/40 px-4 py-3 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="text-lg leading-none mt-0.5 shrink-0">🔔</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
              Reminder
            </span>
          </div>
          <p className="text-sm text-gray-800 dark:text-gray-200 leading-snug">
            {nudge.thing_type_hint && (
              <span className="mr-1">{typeIcon(nudge.thing_type_hint)}</span>
            )}
            {nudge.message}
          </p>
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            {nudge.primary_action_label && nudge.thing_id && (
              <button
                onClick={handlePrimaryAction}
                className="text-xs font-medium px-2.5 py-1 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-400 transition-colors"
              >
                {nudge.primary_action_label}
              </button>
            )}
            <button
              onClick={() => dismissNudge(nudge.id)}
              className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              Got it
            </button>
            <button
              onClick={() => stopNudgeType(nudge.id)}
              className="text-xs text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 transition-colors"
            >
              Stop these
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
