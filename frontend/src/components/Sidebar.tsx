import { useStore } from '../store'
import { ThingCard } from './ThingCard'

function SkeletonCard() {
  return (
    <div className="flex items-start gap-2 px-3 py-2 animate-pulse">
      <div className="w-5 h-5 rounded bg-gray-200 dark:bg-gray-700 shrink-0 mt-0.5" />
      <div className="flex-1 space-y-1.5">
        <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
        <div className="h-2.5 bg-gray-200 dark:bg-gray-700 rounded w-1/3" />
      </div>
    </div>
  )
}

export function Sidebar() {
  const { things, briefing, loading } = useStore(s => ({
    things: s.things,
    briefing: s.briefing,
    loading: s.loading,
  }))

  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const upcoming = things
    .filter(t => {
      if (t.checkin_date == null) return false
      const d = new Date(t.checkin_date)
      d.setHours(0, 0, 0, 0)
      return d > today
    })
    .sort((a, b) => new Date(a.checkin_date!).getTime() - new Date(b.checkin_date!).getTime())

  const active = things.filter(t => t.checkin_date == null)

  // Deduplicate briefing items already shown in upcoming/active
  const briefingIds = new Set(briefing.map(t => t.id))
  const briefingItems = briefing.filter(t => briefingIds.has(t.id))

  return (
    <aside className="w-72 shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 overflow-y-auto">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
        <h1 className="text-lg font-bold text-gray-900 dark:text-white tracking-tight">Reli</h1>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
          {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
      </div>

      {loading && things.length === 0 ? (
        <div className="py-2">
          <div className="px-4 pb-1 mt-1">
            <div className="h-2.5 w-20 bg-gray-200 dark:bg-gray-700 rounded animate-pulse" />
          </div>
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : (
        <>
          {/* Daily Briefing */}
          {briefingItems.length > 0 && (
            <section className="py-2 bg-amber-50 dark:bg-amber-900/10 border-b border-amber-100 dark:border-amber-800/30">
              <h2 className="px-4 pb-1 text-xs font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-widest">
                📅 Daily Briefing
              </h2>
              {briefingItems.map(t => <ThingCard key={t.id} thing={t} />)}
            </section>
          )}

          {/* Upcoming Check-ins */}
          {upcoming.length > 0 && (
            <section className="py-2">
              <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                Upcoming Check-ins
              </h2>
              {upcoming.map(t => <ThingCard key={t.id} thing={t} />)}
            </section>
          )}

          {/* Active Things (no check-in date) */}
          {active.length > 0 && (
            <section className="py-2 border-t border-gray-100 dark:border-gray-800">
              <h2 className="px-4 pb-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                Active Things
              </h2>
              {active.map(t => <ThingCard key={t.id} thing={t} />)}
            </section>
          )}

          {!loading && things.length === 0 && briefingItems.length === 0 && (
            <div className="px-4 py-10 flex flex-col items-center text-center">
              <span className="text-3xl mb-3">🌱</span>
              <p className="text-sm font-medium text-gray-600 dark:text-gray-400">Nothing here yet</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Start by typing in the chat…</p>
            </div>
          )}
        </>
      )}
    </aside>
  )
}
