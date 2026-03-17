import { useCallback } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'

const SECTION_ICONS: Record<string, string> = {
  priorities: '\u{1F3AF}',
  overdue: '\u23F0',
  blockers: '\u{1F6A7}',
  findings: '\u{1F4A1}',
}

export function MorningBriefingCard() {
  const { morningBriefing, markBriefingRead, dismissMorningBriefing } = useStore(
    useShallow(s => ({
      morningBriefing: s.morningBriefing,
      markBriefingRead: s.markBriefingRead,
      dismissMorningBriefing: s.dismissMorningBriefing,
    })),
  )

  const handleMarkRead = useCallback(() => {
    if (morningBriefing) markBriefingRead(morningBriefing.id)
  }, [morningBriefing, markBriefingRead])

  const handleDismiss = useCallback(() => {
    if (morningBriefing) dismissMorningBriefing(morningBriefing.id)
  }, [morningBriefing, dismissMorningBriefing])

  if (!morningBriefing) return null

  const isUnread = !morningBriefing.read_at

  return (
    <section className="py-2 border-b border-gray-100 dark:border-gray-800">
      <div className="px-4 pb-1 flex items-center justify-between">
        <h2 className="text-xs font-semibold text-gray-400 dark:text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
          {isUnread && (
            <span className="inline-block w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          )}
          Morning Briefing
        </h2>
        <button
          onClick={handleDismiss}
          className="text-xs text-gray-400 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          title="Dismiss briefing"
        >
          Dismiss
        </button>
      </div>

      {/* Summary */}
      <div className="px-4 py-1.5">
        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
          {morningBriefing.summary}
        </p>
      </div>

      {/* Sections */}
      {morningBriefing.sections.map(section => (
        <div key={section.key} className="px-4 py-1">
          <h3 className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-0.5 flex items-center gap-1">
            <span>{SECTION_ICONS[section.key] ?? '\u{1F4CB}'}</span>
            {section.title}
          </h3>
          <ul className="space-y-0.5">
            {section.items.map((item, i) => (
              <li key={i} className="text-sm text-gray-600 dark:text-gray-400 flex items-start gap-1.5 pl-1">
                <span className="text-gray-300 dark:text-gray-600 mt-1 text-[8px] leading-none select-none">{'\u25CF'}</span>
                <span className="leading-snug">{item}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {/* Mark as read */}
      {isUnread && (
        <div className="px-4 pt-1 pb-0.5">
          <button
            onClick={handleMarkRead}
            className="text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium transition-colors"
          >
            Mark as read
          </button>
        </div>
      )}
    </section>
  )
}
