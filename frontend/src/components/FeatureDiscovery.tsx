import { useState, useEffect } from 'react'
import { useStore } from '../store'
import { useShallow } from 'zustand/react/shallow'

const STORAGE_KEY = 'reli_seen_features_v1'

function getSeenFeatures(): Set<string> {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return new Set(stored ? JSON.parse(stored) : [])
  } catch {
    return new Set()
  }
}

function markFeatureSeen(feature: string): void {
  const seen = getSeenFeatures()
  seen.add(feature)
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...seen]))
}

interface FeatureHint {
  id: string
  icon: string
  title: string
  description: string
  action?: string
  onAction?: () => void
}

function FeatureHintCard({ hint, onDismiss }: { hint: FeatureHint; onDismiss: () => void }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 bg-gradient-to-r from-violet-50 to-indigo-50 dark:from-violet-950/30 dark:to-indigo-950/30 border border-violet-100 dark:border-violet-800 rounded-lg animate-fade-in-up">
      <span className="text-xl shrink-0 mt-0.5">{hint.icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{hint.title}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">{hint.description}</p>
        <div className="flex items-center gap-3 mt-2">
          {hint.action && hint.onAction && (
            <button
              onClick={() => { hint.onAction!(); onDismiss() }}
              className="text-xs font-medium text-violet-600 dark:text-violet-400 hover:text-violet-800 dark:hover:text-violet-300 transition-colors"
            >
              {hint.action} →
            </button>
          )}
          <button
            onClick={onDismiss}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}

export function FeatureDiscovery() {
  const { nudges, openWeeklyDigest } = useStore(
    useShallow(s => ({ nudges: s.nudges, openWeeklyDigest: s.openWeeklyDigest }))
  )
  const [visibleHints, setVisibleHints] = useState<FeatureHint[]>([])

  useEffect(() => {
    const seen = getSeenFeatures()
    const hints: FeatureHint[] = []

    if (!seen.has('nudge-banners') && nudges.length > 0) {
      hints.push({
        id: 'nudge-banners',
        icon: '💡',
        title: 'Proactive nudges',
        description: 'Reli now surfaces timely reminders above the chat — dismiss or stop them anytime.',
      })
    }

    if (!seen.has('weekly-digest')) {
      hints.push({
        id: 'weekly-digest',
        icon: '📊',
        title: 'New: Weekly Digest',
        description: 'See a summary of your week — completed tasks, new connections, and upcoming deadlines.',
        action: 'View digest',
        onAction: openWeeklyDigest,
      })
    }

    if (!seen.has('push-notifications') && 'Notification' in window && 'PushManager' in window) {
      hints.push({
        id: 'push-notifications',
        icon: '🔔',
        title: 'New: Push Notifications',
        description: 'Enable push notifications in Settings → Notifications to get reminders even when Reli is closed.',
      })
    }

    setVisibleHints(hints.slice(0, 1)) // Show one hint at a time
  }, [nudges.length, openWeeklyDigest])

  const dismissHint = (id: string) => {
    markFeatureSeen(id)
    setVisibleHints(prev => prev.filter(h => h.id !== id))
  }

  if (visibleHints.length === 0) return null

  return (
    <div className="flex flex-col gap-2 px-3 pt-2 pb-0">
      {visibleHints.map(hint => (
        <FeatureHintCard key={hint.id} hint={hint} onDismiss={() => dismissHint(hint.id)} />
      ))}
    </div>
  )
}
